"""
Worker 7 Web Server Wrapper — Doc 08 contract
==============================================

Identical shape to W3/W4/W6: POST /process + X-Webhook-Secret ->
validate -> idempotency -> claim -> 202 -> async. GET /health.
503 unconfigured secret; 401 mismatch.
"""

import logging
import os
import threading

from flask import Flask, jsonify, request

from pronto_worker_7 import JournalProcessor, WORKER_VERSION

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'service': 'worker_7_journal',
        'version': WORKER_VERSION,
    })


@app.route('/process', methods=['POST'])
def process():
    secret = os.getenv('WEBHOOK_SECRET')
    if not secret:
        logger.error("WEBHOOK_SECRET is not configured")
        return jsonify({'success': False,
                        'error': 'Server missing WEBHOOK_SECRET configuration'}), 503
    if request.headers.get('X-Webhook-Secret') != secret:
        return jsonify({'success': False, 'error': 'Invalid webhook secret'}), 401

    data = request.get_json(silent=True)
    if not data or 'service_id' not in data:
        return jsonify({'success': False,
                        'error': 'Missing service_id in request body'}), 400
    service_id = data['service_id']

    try:
        processor = JournalProcessor()
        service = processor.airtable_client.get_service(service_id)
        if not service:
            return jsonify({'success': False,
                            'error': f'Service {service_id} not found'}), 404
        noop = processor.check_idempotency(service, service_id)
        if noop:
            return jsonify(noop), 200
        processor.claim(service_id)

        def _work():
            try:
                processor.process_service(service_id, already_claimed=True)
            except Exception:
                logger.exception(f"Async processing crashed for {service_id}")

        threading.Thread(target=_work, daemon=True).start()
        return jsonify({'success': True, 'status': 'accepted',
                        'service_id': service_id,
                        'message': 'Claimed; processing asynchronously'}), 202
    except Exception as e:
        logger.error(f"Error handling request: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
