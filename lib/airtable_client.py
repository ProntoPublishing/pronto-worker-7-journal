"""
Airtable Client
===============

Interacts with Airtable Services table.

Author: Pronto Publishing
Version: 1.1.0
"""

import os
import logging
from typing import Dict, Any, Optional
from pyairtable import Api

logger = logging.getLogger(__name__)


class AirtableClient:
    """Client for Airtable Services table."""
    
    def __init__(self):
        """Initialize Airtable client."""
        self.token = os.getenv('AIRTABLE_TOKEN')
        self.base_id = os.getenv('AIRTABLE_BASE_ID')
        self.table_name = "Services"
        
        if not self.token:
            raise ValueError("AIRTABLE_TOKEN environment variable not set")
        if not self.base_id:
            raise ValueError("AIRTABLE_BASE_ID environment variable not set")
        
        self.api = Api(self.token)
        self.table = self.api.table(self.base_id, self.table_name)
        
        logger.info(f"Airtable client initialized: {self.base_id}/{self.table_name}")
    
    def get_service(self, service_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Service record by ID.
        
        Args:
            service_id: Airtable record ID
            
        Returns:
            Service record fields or None if not found
        """
        try:
            record = self.table.get(service_id)
            return record['fields']
        except Exception as e:
            logger.error(f"Failed to get service {service_id}: {e}")
            return None
    
    def update_service(self, service_id: str, fields: Dict[str, Any],
                       typecast: bool = False) -> bool:
        """
        Update Service record.

        Args:
            service_id: Airtable record ID
            fields: Fields to update
            typecast: pass True ONLY for writes that may carry a select
                option Airtable hasn't seen yet (the "Review" status —
                Gate 2 ruling Q4); Airtable then creates the option on
                first write. Kept False everywhere else so typos in
                select values still fail loudly.

        Returns:
            True if successful, False otherwise
        """
        try:
            self.table.update(service_id, fields, typecast=typecast)
            logger.info(f"Updated service {service_id}: {list(fields.keys())}")
            return True
        except Exception as e:
            logger.error(f"Failed to update service {service_id}: {e}")
            return False
    
    def get_service_type(self, service_type_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Service Type record from Service Catalog table.
        
        Args:
            service_type_id: Airtable record ID
            
        Returns:
            Service Type record fields or None if not found
        """
        try:
            service_catalog_table = self.api.table(self.base_id, 'Service Catalog')
            record = service_catalog_table.get(service_type_id)
            return record['fields']
        except Exception as e:
            logger.error(f"Failed to get service type {service_type_id}: {e}")
            return None
    
    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Project record.
        
        Args:
            project_id: Airtable record ID
            
        Returns:
            Project record fields or None if not found
        """
        try:
            projects_table = self.api.table(self.base_id, 'Projects')
            record = projects_table.get(project_id)
            return record['fields']
        except Exception as e:
            logger.error(f"Failed to get project {project_id}: {e}")
            return None
    
    def get_book_metadata(self, metadata_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Book Metadata record.
        
        Args:
            metadata_id: Airtable record ID
            
        Returns:
            Book Metadata record fields or None if not found
        """
        try:
            metadata_table = self.api.table(self.base_id, 'Book Metadata')
            record = metadata_table.get(metadata_id)
            return record['fields']
        except Exception as e:
            logger.error(f"Failed to get book metadata {metadata_id}: {e}")
            return None

    # --- E4 additions (2026-07-19): Imprints table readers -----------------
    def get_imprint(self, imprint_id: str) -> Optional[Dict[str, Any]]:
        """One Imprints row by record id (E4)."""
        try:
            t = self.api.table(self.base_id, 'Imprints')
            return t.get(imprint_id)['fields']
        except Exception as e:
            logger.error(f"Failed to get imprint {imprint_id}: {e}")
            return None

    def get_default_imprint(self) -> Optional[Dict[str, Any]]:
        """The single E4 Default row (Landfall Ink per governance §7).
        Seven-row table — a full scan is cheap and needs no formula."""
        try:
            t = self.api.table(self.base_id, 'Imprints')
            for rec in t.all():
                if rec['fields'].get('E4 Default'):
                    return rec['fields']
        except Exception as e:
            logger.error(f"Failed to scan Imprints for default: {e}")
        return None
