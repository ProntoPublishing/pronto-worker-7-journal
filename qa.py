"""
QA Reviewer v0 (QA_Reviewer_WorkOrder_v0 2026-07-21) — identical
module vendored into every producing worker (W2/W3/W4/W7/W8), the
imprint.py pattern. Deterministic KDP-readiness checks on each
customer-facing deliverable, run inline as the worker's final step
before it asserts Status=Complete. Flags only — QA never marks a
service Complete on its own; it validates what the worker produced
and records a verdict.

Posture (rulings 2026-07-22):
- Report-only soak is TRULY INERT: `QA Status`=Pass on pass and the
  full report always, but a failing service keeps `QA Status`=Pending
  (writing Fail would trip the Failed QA Count rollup and gate
  delivery mid-soak) with the report headed "Fail (report-only)".
- Gating mode (env QA_GATING_ENABLED=true): Fail + Blocked +
  Blocked Reason, and the worker holds the service at Status=Review
  instead of Complete. Artifact fields are written either way.
- Severities: "fail" blocks when gating is on; "warn" records and
  never blocks; "note" is informational (including checks v0 honestly
  cannot run); "pass". A crashed check is a warn (qa_internal:*) —
  QA must never become a new outage mode; only affirmative
  deterministic findings gate.
- Constants are re-derived here, never imported from a worker's
  geometry module (W4 validate.py rationale): if a worker's math
  drifts, QA catches it rather than inheriting it.
- Determinism: no wall clock, paths, or object ids in verdict text;
  fixed check order; same artifact -> byte-identical report, so
  re-runs never thrash Airtable.

Author: Pronto Publishing
"""

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import IndirectObject

QA_VERSION = "0.1.0"

POINTS_PER_INCH = 72.0
BLEED_IN = 0.125
DIM_TOL_IN = 0.001                      # page-dimension tolerance (audit_pdf/W4 canon)
DIM_TOL_PT = DIM_TOL_IN * POINTS_PER_INCH

MIN_PDF_BYTES = 1024                    # anything smaller is not a real deliverable
PDF_HEADER_SCAN = 1024                  # %PDF- header may sit after a BOM/prefix (spec)

INTERIOR_MIN_PAGES = 24                 # KDP paperback bounds
INTERIOR_MAX_PAGES = 828

# KDP spine factors, inches per page (KDP paperback build spec).
PAPER_FACTORS_IN_PER_PAGE = {
    "white": 0.002252,
    "cream": 0.0025,
    "premium color": 0.002347,
}
SPINE_TEXT_MIN_PAGES = 79               # below this the spine must be blank

# KDP inside-margin (gutter) floor by TOTAL page count.
GUTTER_BRACKETS = (
    (24, 150, 0.375),
    (151, 300, 0.5),
    (301, 500, 0.625),
    (501, 700, 0.75),
    (701, 828, 0.875),
)

MIN_IMAGE_DPI = 300.0
MIN_IMAGE_PX = 8                        # skip masks/hairline strips
MAX_DPI_OFFENDERS = 5                   # bound the report, deterministically

ARTIFACT_INTERIOR = "Interior PDF"
ARTIFACT_COVER = "Cover PDF"
ARTIFACT_KDP_ZIP = "KDP Upload Package ZIP"

_TRUE_LITERALS = ("1", "true", "yes")


class QAExtractionError(Exception):
    """Artifact could not be reduced to facts (unreadable PDF/zip)."""


# ---------------------------------------------------------------------------
# Config / spec / verdicts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QAConfig:
    gating_enabled: bool = False
    max_report_chars: int = 8000

    @classmethod
    def from_env(cls) -> "QAConfig":
        raw = (os.getenv("QA_GATING_ENABLED") or "").strip().lower()
        return cls(gating_enabled=raw in _TRUE_LITERALS)

    @property
    def mode(self) -> str:
        return "gating" if self.gating_enabled else "report-only"


@dataclass(frozen=True)
class QASpec:
    """What the worker expects of its own artifact. All values are the
    worker's declared truth — QA re-measures the artifact against them."""
    artifact_type: str                          # ARTIFACT_* literal
    trim: Tuple[float, float]                   # inches (w, h), already parsed
    page_count: int                             # TOTAL interior printed pages
    paper: str = "cream"                        # cover/zip spine math input
    inside_margin_in: Optional[float] = None    # declared gutter (interiors)
    manifest_member_shas: Optional[Dict[str, str]] = None   # zip: promised sha256s
    sibling_interior_sha256: Optional[str] = None           # zip chain of custody
    sibling_cover_sha256: Optional[str] = None
    r2_key: Optional[str] = None                # uploaded object key, for check 9


@dataclass(frozen=True)
class QAVerdict:
    check: str
    ok: bool
    severity: str                               # "pass" | "fail" | "warn" | "note"
    detail: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"check": self.check, "ok": self.ok,
                "severity": self.severity, "detail": self.detail}


@dataclass
class QAResult:
    verdicts: List[QAVerdict] = field(default_factory=list)

    @property
    def hard_fails(self) -> List[QAVerdict]:
        return [v for v in self.verdicts if v.severity == "fail" and not v.ok]

    @property
    def warnings(self) -> List[QAVerdict]:
        return [v for v in self.verdicts if v.severity == "warn" and not v.ok]

    @property
    def passed(self) -> bool:
        return not self.hard_fails

    def should_block(self, config: QAConfig) -> bool:
        return config.gating_enabled and not self.passed

    def report_lines(self) -> List[str]:
        lines = []
        for v in self.verdicts:
            tag = "PASS" if v.ok else v.severity.upper()
            lines.append(f"{tag} {v.check}" + (f": {v.detail}" if v.detail else ""))
        return lines

    def hold_summary(self) -> str:
        """Short human summary for Blocked Reason (daily scan + hold email)."""
        return "; ".join(
            f"{v.check}: {v.detail}" if v.detail else v.check
            for v in self.hard_fails
        )

    def airtable_fields(self, config: QAConfig) -> Dict[str, str]:
        """QA Status + QA Report per the 2026-07-22 soak ruling. The
        worker merges this into its final Service write; Blocked fields
        come from blocked_fields() only when should_block()."""
        n_hard, n_warn = len(self.hard_fails), len(self.warnings)
        if self.passed:
            verdict_word = "Pass"
        elif config.gating_enabled:
            verdict_word = "Fail"
        else:
            verdict_word = "Fail (report-only)"
        header = (f"qa {QA_VERSION} | {config.mode} | {verdict_word} "
                  f"({n_hard} hard, {n_warn} warn)")
        body = "\n".join([header] + self.report_lines())
        if len(body) > config.max_report_chars:
            kept = []
            size = len(header) + 1
            dropped = 0
            for line in self.report_lines():
                if size + len(line) + 1 <= config.max_report_chars - 32:
                    kept.append(line)
                    size += len(line) + 1
                else:
                    dropped += 1
            body = "\n".join([header] + kept +
                             [f"... (+{dropped} lines truncated)"])
        fields = {"QA Report": body}
        if self.passed:
            fields["QA Status"] = "Pass"
        elif config.gating_enabled:
            fields["QA Status"] = "Fail"
        # report-only fail: QA Status stays Pending — a Fail write would
        # trip the Failed QA Count rollup and gate delivery mid-soak.
        return fields

    def blocked_fields(self) -> Dict[str, Any]:
        return {"Blocked": True, "Blocked Reason": self.hold_summary()}


# ---------------------------------------------------------------------------
# Extraction (the only layer that touches pypdf / zipfile / boto3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FontFact:
    base_name: str
    embedded: bool
    is_type3: bool


@dataclass(frozen=True)
class ImageFact:
    page_index: int
    name: str
    px_w: int
    px_h: int


@dataclass(frozen=True)
class PdfFacts:
    page_count: int
    page_sizes_pt: Tuple[Tuple[float, float], ...]
    fonts: Tuple[FontFact, ...]
    images: Tuple[ImageFact, ...]


@dataclass(frozen=True)
class ZipFacts:
    names: Tuple[str, ...]                      # zip order
    member_shas: Dict[str, str]                 # name -> sha256 hex
    corrupt_member: Optional[str]               # first bad CRC, or None


def _resolve(obj: Any) -> Any:
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def _font_key(name: Any, ref: Any) -> Any:
    if isinstance(ref, IndirectObject):
        return ("obj", ref.idnum, getattr(ref, "generation", 0))
    return ("name", str(name))


def extract_pdf_facts(pdf_bytes: bytes) -> PdfFacts:
    """Reduce a PDF to plain-value facts. Raises QAExtractionError on
    an unreadable document; per-page resource oddities never raise."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        n = len(reader.pages)
    except Exception as e:            # pypdf raises a small zoo here
        raise QAExtractionError(f"{type(e).__name__}: {e}") from e

    sizes: List[Tuple[float, float]] = []
    fonts: List[FontFact] = []
    images: List[ImageFact] = []
    seen_fonts = set()

    for idx in range(n):
        page = reader.pages[idx]
        box = page.mediabox
        sizes.append((float(box.width), float(box.height)))

        resources = _resolve(page.get("/Resources")) or {}

        font_dict = _resolve(resources.get("/Font")) or {}
        for name, ref in font_dict.items():
            key = _font_key(name, ref)
            if key in seen_fonts:
                continue
            seen_fonts.add(key)
            font = _resolve(ref)
            if not hasattr(font, "get"):
                continue
            base = str(font.get("/BaseFont", name))
            is_type3 = str(font.get("/Subtype", "")) == "/Type3"
            descriptor = font
            if "/DescendantFonts" in font:      # Type0/CID path
                descendants = _resolve(font["/DescendantFonts"])
                descriptor = _resolve(descendants[0])
            fd = _resolve(descriptor.get("/FontDescriptor"))
            embedded = bool(fd) and any(
                k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))
            fonts.append(FontFact(base, embedded, is_type3))

        xobjects = _resolve(resources.get("/XObject")) or {}
        for name, ref in xobjects.items():
            xobj = _resolve(ref)
            if not hasattr(xobj, "get"):
                continue
            if str(xobj.get("/Subtype", "")) != "/Image":
                continue
            try:
                px_w = int(xobj.get("/Width", 0))
                px_h = int(xobj.get("/Height", 0))
            except (TypeError, ValueError):
                continue
            images.append(ImageFact(idx, str(name), px_w, px_h))

    return PdfFacts(n, tuple(sizes), tuple(fonts), tuple(images))


def extract_zip_facts(zip_bytes: bytes) -> ZipFacts:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except Exception as e:
        raise QAExtractionError(f"{type(e).__name__}: {e}") from e
    with zf:
        corrupt = zf.testzip()
        names = tuple(zf.namelist())
        shas = {name: hashlib.sha256(zf.read(name)).hexdigest()
                for name in names}
    return ZipFacts(names, shas, corrupt)


def _norm_sha(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    return v[len("sha256:"):] if v.startswith("sha256:") else v


# ---------------------------------------------------------------------------
# Checks — pure functions (facts, spec) -> QAVerdict
# ---------------------------------------------------------------------------

def check_pdf_integrity(pdf_bytes: bytes) -> QAVerdict:
    if len(pdf_bytes) < MIN_PDF_BYTES:
        return QAVerdict("pdf_integrity", False, "fail",
                         f"artifact is {len(pdf_bytes)} bytes "
                         f"(< {MIN_PDF_BYTES} minimum)")
    if b"%PDF-" not in pdf_bytes[:PDF_HEADER_SCAN]:
        return QAVerdict("pdf_integrity", False, "fail",
                         "no %PDF- header in the first "
                         f"{PDF_HEADER_SCAN} bytes")
    try:
        facts = extract_pdf_facts(pdf_bytes)
    except QAExtractionError as e:
        return QAVerdict("pdf_integrity", False, "fail",
                         f"unreadable PDF ({e})")
    if facts.page_count < 1:
        return QAVerdict("pdf_integrity", False, "fail", "PDF has 0 pages")
    return QAVerdict("pdf_integrity", True, "pass",
                     f"{facts.page_count} pages, {len(pdf_bytes)} bytes")


def check_page_count(facts: PdfFacts, spec: QASpec) -> QAVerdict:
    n = facts.page_count
    if spec.artifact_type == ARTIFACT_COVER:
        if n != 1:
            return QAVerdict("page_count", False, "fail",
                             f"cover must be 1 page, found {n}")
        return QAVerdict("page_count", True, "pass", "1 page")
    problems = []
    if not (INTERIOR_MIN_PAGES <= n <= INTERIOR_MAX_PAGES):
        problems.append(f"{n} pages outside KDP bounds "
                        f"{INTERIOR_MIN_PAGES}-{INTERIOR_MAX_PAGES}")
    if n != spec.page_count:
        problems.append(f"counted {n} != expected {spec.page_count}")
    if problems:
        return QAVerdict("page_count", False, "fail", "; ".join(problems))
    return QAVerdict("page_count", True, "pass", f"{n} pages")


def expected_cover_dims(page_count: int, paper: str,
                        trim: Tuple[float, float]) -> Tuple[float, float]:
    factor = PAPER_FACTORS_IN_PER_PAGE[(paper or "cream").strip().lower()]
    spine = page_count * factor
    trim_w, trim_h = trim
    return (BLEED_IN + trim_w + spine + trim_w + BLEED_IN,
            BLEED_IN + trim_h + BLEED_IN)


def check_page_geometry(facts: PdfFacts, spec: QASpec) -> QAVerdict:
    if spec.artifact_type == ARTIFACT_COVER:
        paper = (spec.paper or "cream").strip().lower()
        if paper not in PAPER_FACTORS_IN_PER_PAGE:
            return QAVerdict("page_geometry", False, "fail",
                             f"unknown paper stock {paper!r}")
        exp_w, exp_h = expected_cover_dims(spec.page_count, paper, spec.trim)
        got_w, got_h = facts.page_sizes_pt[0]
        got_w_in, got_h_in = got_w / POINTS_PER_INCH, got_h / POINTS_PER_INCH
        if (abs(got_w_in - exp_w) > DIM_TOL_IN
                or abs(got_h_in - exp_h) > DIM_TOL_IN):
            return QAVerdict(
                "page_geometry", False, "fail",
                f"wrap is {got_w_in:.4f}x{got_h_in:.4f}in, expected "
                f"{exp_w:.4f}x{exp_h:.4f}in (trim {spec.trim[0]}x"
                f"{spec.trim[1]}, {spec.page_count}pp {paper})")
        return QAVerdict("page_geometry", True, "pass",
                         f"full wrap {exp_w:.4f}x{exp_h:.4f}in")
    # Interior: every page exactly trim (W2/W7/W8 render no-bleed
    # trim-exact — validated as-shipped; full-bleed language in the
    # work order is a spec erratum flagged to governance).
    exp_w_pt = spec.trim[0] * POINTS_PER_INCH
    exp_h_pt = spec.trim[1] * POINTS_PER_INCH
    bad = 0
    first = None
    for idx, (w, h) in enumerate(facts.page_sizes_pt):
        if abs(w - exp_w_pt) > DIM_TOL_PT or abs(h - exp_h_pt) > DIM_TOL_PT:
            bad += 1
            if first is None:
                first = (idx, w, h)
    if bad:
        idx, w, h = first
        return QAVerdict(
            "page_geometry", False, "fail",
            f"{bad} page(s) off-trim; first: page {idx + 1} is "
            f"{w:.2f}x{h:.2f}pt, expected {exp_w_pt:.2f}x{exp_h_pt:.2f}pt")
    return QAVerdict("page_geometry", True, "pass",
                     f"all pages {spec.trim[0]}x{spec.trim[1]}in")


def check_fonts_embedded(facts: PdfFacts) -> QAVerdict:
    missing = sorted({f.base_name for f in facts.fonts
                      if not f.embedded and not f.is_type3})
    if missing:
        return QAVerdict("font_embedding", False, "fail",
                         "not embedded: " + ", ".join(missing))
    return QAVerdict("font_embedding", True, "pass",
                     f"{len(facts.fonts)} font(s), all embedded")


def check_image_dpi(facts: PdfFacts) -> QAVerdict:
    """One-sided lower bound: dpi_lb = px / full-page-inches. >= 300
    proves the image safe at ANY placement up to full-page width; below
    only means POSSIBLY bad (it may be placed smaller), so this check
    can warn but never hard-fail. Workers enforce >=300 input-side."""
    offenders = []
    for img in facts.images:
        if img.px_w <= MIN_IMAGE_PX or img.px_h <= MIN_IMAGE_PX:
            continue
        page_w_in = facts.page_sizes_pt[img.page_index][0] / POINTS_PER_INCH
        page_h_in = facts.page_sizes_pt[img.page_index][1] / POINTS_PER_INCH
        dpi_lb = min(img.px_w / page_w_in, img.px_h / page_h_in)
        if dpi_lb < MIN_IMAGE_DPI:
            offenders.append((img.page_index + 1, img.name, dpi_lb))
    if offenders:
        offenders.sort(key=lambda o: (o[2], o[0], o[1]))
        shown = ", ".join(f"p{p} {n} ~{d:.0f}dpi"
                          for p, n, d in offenders[:MAX_DPI_OFFENDERS])
        extra = len(offenders) - min(len(offenders), MAX_DPI_OFFENDERS)
        if extra > 0:
            shown += f" (+{extra} more)"
        return QAVerdict(
            "image_dpi", False, "warn",
            f"{len(offenders)} image(s) below 300dpi IF placed full-page "
            f"(lower-bound test; may be placed smaller): {shown}")
    return QAVerdict("image_dpi", True, "pass",
                     f"{len(facts.images)} image(s), none below the "
                     "300dpi lower bound")


def gutter_floor_in(page_count: int) -> Optional[float]:
    for lo, hi, floor in GUTTER_BRACKETS:
        if lo <= page_count <= hi:
            return floor
    return None


def check_gutter_declared(spec: QASpec) -> QAVerdict:
    if spec.inside_margin_in is None:
        return QAVerdict("gutter_declared", True, "note",
                         "gutter not measurable in v0 "
                         "(no declared inside margin passed)")
    floor = gutter_floor_in(spec.page_count)
    if floor is None:
        return QAVerdict("gutter_declared", True, "note",
                         f"page count {spec.page_count} outside gutter "
                         "bracket table (page_count check governs)")
    if spec.inside_margin_in < floor:
        return QAVerdict(
            "gutter_declared", False, "fail",
            f"declared inside margin {spec.inside_margin_in}in below KDP "
            f"floor {floor}in for {spec.page_count}pp")
    return QAVerdict("gutter_declared", True, "pass",
                     f"declared {spec.inside_margin_in}in >= floor "
                     f"{floor}in ({spec.page_count}pp)")


def check_spine_posture(spec: QASpec) -> QAVerdict:
    factor = PAPER_FACTORS_IN_PER_PAGE.get(
        (spec.paper or "cream").strip().lower())
    spine = spec.page_count * factor if factor else None
    if spec.page_count >= SPINE_TEXT_MIN_PAGES:
        detail = f"spine text permitted ({spec.page_count}pp"
        if spine is not None:
            detail += f", spine {spine:.4f}in"
        return QAVerdict("spine_posture", True, "note", detail + ")")
    return QAVerdict(
        "spine_posture", True, "note",
        f"spine must be blank (<{SPINE_TEXT_MIN_PAGES}pp); ink-in-zone "
        "not verifiable with pypdf in v0 (renderer enforces)")


def check_zip_structure(zfacts: ZipFacts, spec: QASpec) -> List[QAVerdict]:
    verdicts = []
    if zfacts.corrupt_member is not None:
        verdicts.append(QAVerdict("zip_integrity", False, "fail",
                                  f"CRC failure in {zfacts.corrupt_member}"))
    else:
        verdicts.append(QAVerdict("zip_integrity", True, "pass",
                                  f"{len(zfacts.names)} members, CRC clean"))

    promised = spec.manifest_member_shas or {}
    if promised:
        missing = sorted(set(promised) - set(zfacts.names))
        extra = sorted(set(zfacts.names) - set(promised))
        if missing or extra:
            bits = []
            if missing:
                bits.append("missing: " + ", ".join(missing))
            if extra:
                bits.append("unexpected: " + ", ".join(extra))
            verdicts.append(QAVerdict("zip_members", False, "fail",
                                      "; ".join(bits)))
        else:
            verdicts.append(QAVerdict("zip_members", True, "pass",
                                      "members match manifest promise"))
        mismatched = sorted(
            name for name, sha in promised.items()
            if name in zfacts.member_shas
            and _norm_sha(zfacts.member_shas[name]) != _norm_sha(sha))
        if mismatched:
            verdicts.append(QAVerdict(
                "zip_member_shas", False, "fail",
                "sha256 mismatch vs manifest: " + ", ".join(mismatched)))
        else:
            verdicts.append(QAVerdict("zip_member_shas", True, "pass",
                                      "member sha256s match manifest"))
    else:
        verdicts.append(QAVerdict("zip_members", True, "note",
                                  "no manifest member promise supplied"))

    for member, promised_sha, label in (
            ("interior.pdf", spec.sibling_interior_sha256, "interior"),
            ("cover.pdf", spec.sibling_cover_sha256, "cover")):
        if not promised_sha:
            verdicts.append(QAVerdict(
                f"zip_custody_{label}", True, "note",
                f"no sibling {label} sha supplied"))
            continue
        got = zfacts.member_shas.get(member)
        if got is None:
            verdicts.append(QAVerdict(
                f"zip_custody_{label}", False, "fail",
                f"{member} absent from package"))
        elif _norm_sha(got) != _norm_sha(promised_sha):
            verdicts.append(QAVerdict(
                f"zip_custody_{label}", False, "fail",
                f"{member} sha256 != the sibling service's artifact "
                "(stale or substituted member)"))
        else:
            verdicts.append(QAVerdict(
                f"zip_custody_{label}", True, "pass",
                f"{member} matches the sibling service's artifact"))
    return verdicts


def check_r2_object(r2: Any, key: str, expected_len: int) -> QAVerdict:
    """The module's only I/O check. Missing/truncated object is an
    affirmative finding; a transient error is infra flake and must not
    gate. Duck-typed: needs r2.s3_client + r2.bucket_name."""
    try:
        head = r2.s3_client.head_object(Bucket=r2.bucket_name, Key=key)
    except Exception as e:
        code = ""
        resp = getattr(e, "response", None)
        if isinstance(resp, dict):
            code = str(resp.get("Error", {}).get("Code", ""))
        if code in ("404", "NoSuchKey", "NotFound"):
            return QAVerdict("r2_object", False, "fail",
                             f"uploaded object missing: {key}")
        return QAVerdict("r2_object", False, "warn",
                         f"R2 HEAD errored ({type(e).__name__}); "
                         "not gating on infra flake")
    content_length = head.get("ContentLength")
    if content_length is not None and content_length != expected_len:
        return QAVerdict(
            "r2_object", False, "fail",
            f"size mismatch: R2 has {content_length} bytes, artifact is "
            f"{expected_len} (truncated upload?)")
    return QAVerdict("r2_object", True, "pass",
                     f"present in R2 ({expected_len} bytes)")


# ---------------------------------------------------------------------------
# Review driver
# ---------------------------------------------------------------------------

def _guard(verdicts: List[QAVerdict], name: str, fn, *args) -> None:
    """A crashed check is a warn, never a gate and never an outage —
    only affirmative deterministic findings block."""
    try:
        out = fn(*args)
    except Exception as e:
        verdicts.append(QAVerdict(f"qa_internal:{name}", False, "warn",
                                  f"check crashed: {type(e).__name__}: {e}"))
        return
    if isinstance(out, list):
        verdicts.extend(out)
    else:
        verdicts.append(out)


def _as_bytes(artifact: Union[bytes, str, os.PathLike]) -> bytes:
    if isinstance(artifact, bytes):
        return artifact
    with open(artifact, "rb") as fh:
        return fh.read()


def _review_pdf(data: bytes, spec: QASpec,
                gutter: bool) -> List[QAVerdict]:
    verdicts: List[QAVerdict] = []
    integrity = check_pdf_integrity(data)
    verdicts.append(integrity)
    if not integrity.ok:
        verdicts.append(QAVerdict(
            "pdf_checks_skipped", True, "note",
            "downstream PDF checks skipped: artifact unreadable"))
        return verdicts
    facts = extract_pdf_facts(data)
    _guard(verdicts, "page_count", check_page_count, facts, spec)
    _guard(verdicts, "page_geometry", check_page_geometry, facts, spec)
    _guard(verdicts, "font_embedding", check_fonts_embedded, facts)
    _guard(verdicts, "image_dpi", check_image_dpi, facts)
    if spec.artifact_type == ARTIFACT_COVER:
        _guard(verdicts, "spine_posture", check_spine_posture, spec)
    elif gutter:
        _guard(verdicts, "gutter_declared", check_gutter_declared, spec)
    return verdicts


def review(*, artifact: Union[bytes, str, os.PathLike], spec: QASpec,
           r2: Any = None, config: Optional[QAConfig] = None) -> QAResult:
    config = config or QAConfig.from_env()
    data = _as_bytes(artifact)
    verdicts: List[QAVerdict] = []

    if spec.artifact_type == ARTIFACT_KDP_ZIP:
        try:
            zfacts = extract_zip_facts(data)
        except QAExtractionError as e:
            verdicts.append(QAVerdict("zip_integrity", False, "fail",
                                      f"unreadable zip ({e})"))
            zfacts = None
        if zfacts is not None:
            _guard(verdicts, "zip_structure", check_zip_structure,
                   zfacts, spec)
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "interior.pdf" in names:
                    interior_spec = QASpec(
                        artifact_type=ARTIFACT_INTERIOR, trim=spec.trim,
                        page_count=spec.page_count, paper=spec.paper)
                    for v in _review_pdf(zf.read("interior.pdf"),
                                         interior_spec, gutter=True):
                        verdicts.append(QAVerdict(
                            f"interior.{v.check}", v.ok, v.severity,
                            v.detail))
                if "cover.pdf" in names:
                    cover_spec = QASpec(
                        artifact_type=ARTIFACT_COVER, trim=spec.trim,
                        page_count=spec.page_count, paper=spec.paper)
                    for v in _review_pdf(zf.read("cover.pdf"),
                                         cover_spec, gutter=False):
                        verdicts.append(QAVerdict(
                            f"cover.{v.check}", v.ok, v.severity,
                            v.detail))
    elif spec.artifact_type in (ARTIFACT_INTERIOR, ARTIFACT_COVER):
        verdicts.extend(_review_pdf(data, spec, gutter=True))
    else:
        verdicts.append(QAVerdict(
            "qa_dispatch", False, "fail",
            f"unknown artifact type {spec.artifact_type!r} — "
            "miswired call site"))

    if r2 is not None and spec.r2_key:
        _guard(verdicts, "r2_object", check_r2_object,
               r2, spec.r2_key, len(data))
    else:
        verdicts.append(QAVerdict("r2_object", True, "note",
                                  "R2 check skipped (no client/key)"))

    return QAResult(verdicts)
