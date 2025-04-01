# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class DocumentSearch:
    """Interface for searching indexed documents"""

    def __init__(self, index_manager):
        """
        Initialize document search

        Args:
            index_manager: The document index manager instance
        """
        self.index_manager = index_manager

    async def search(
        self,
        query: str,
        limit: int = 5,
        file_types: Optional[List[str]] = None,
        directories: Optional[List[str]] = None,
        recency: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for documents matching the query

        Args:
            query: The search query
            limit: Maximum number of results to return
            file_types: Optional list of file extensions to filter by
            directories: Optional list of directories to search in
            recency: Optional recency filter (e.g., "today", "this week", "this month")

        Returns:
            Dictionary with search results and metadata
        """
        logger.info(f"Searching documents with query: {query}")

        # Get raw search results
        results = self.index_manager.search(query, limit=limit)

        # Apply filters
        filtered_results = self._apply_filters(
            results,
            file_types=file_types,
            directories=directories,
            recency=recency
        )

        # Limit results
        limited_results = filtered_results[:limit]

        # Group results by document
        grouped_results = self._group_by_document(limited_results)

        return {
            "success": True,
            "query": query,
            "results": grouped_results,
            "total_results": len(filtered_results),
            "limited_results": len(limited_results),
            "filters_applied": {
                "file_types": file_types,
                "directories": directories,
                "recency": recency
            }
        }

    def _apply_filters(
        self,
        results: List[Dict[str, Any]],
        file_types: Optional[List[str]] = None,
        directories: Optional[List[str]] = None,
        recency: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Apply filters to search results"""
        filtered = results

        # Filter by file type
        if file_types:
            filtered = [
                r for r in filtered
                if any(r.get("filepath", "").lower().endswith(ft.lower()) for ft in file_types)
            ]

        # Filter by directory
        if directories:
            filtered = [
                r for r in filtered
                if any(r.get("filepath", "").startswith(d) for d in directories)
            ]

        # Filter by recency
        if recency:
            now = datetime.now()
            cutoff = None

            if recency == "today":
                cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif recency == "yesterday":
                cutoff = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            elif recency == "this week":
                cutoff = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            elif recency == "this month":
                cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif recency == "this year":
                cutoff = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

            if cutoff:
                filtered = [
                    r for r in filtered
                    if self._parse_date(r.get("last_modified", "")) >= cutoff
                ]

        return filtered

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime object"""
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return datetime.min

    def _group_by_document(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group results by document to avoid duplicates"""
        grouped = {}

        for result in results:
            filepath = result.get("filepath")
            if filepath not in grouped:
                grouped[filepath] = {
                    "filename": result.get("filename"),
                    "filepath": filepath,
                    "file_type": result.get("file_type"),
                    "last_modified": result.get("last_modified"),
                    "snippets": []
                }

            grouped[filepath]["snippets"].append({
                "content": result.get("content_snippet"),
                "chunk_index": result.get("chunk_index", 0),
                "total_chunks": result.get("total_chunks", 1)
            })

        return list(grouped.values())
