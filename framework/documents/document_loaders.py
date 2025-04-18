# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.


import os
import logging
from typing import Optional, Dict, Any

# Import LangChain document loaders
try:
    from langchain.document_loaders import (
        TextLoader, 
        PyPDFLoader, 
        UnstructuredWordDocumentLoader,
        UnstructuredPowerPointLoader,
        CSVLoader,
        UnstructuredExcelLoader,
        JSONLoader
    )
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    DOCUMENT_LOADERS_AVAILABLE = True
except ImportError:
    DOCUMENT_LOADERS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default text splitter configuration
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200

def get_document_loader(file_path: str) -> Optional[Any]:
    """
    Get the appropriate document loader for a file
    
    Args:
        file_path: Path to the file
        
    Returns:
        A document loader instance or None if no suitable loader is found
    """
    if not DOCUMENT_LOADERS_AVAILABLE:
        logger.error("Document loaders not available. Install with: pip install "
                    "langchain chromadb sentence-transformers unstructured")
        return None
        
    if not os.path.exists(file_path):
        logger.error(f"File does not exist: {file_path}")
        return None
        
    # Get file extension
    _, ext = os.path.splitext(file_path.lower())
    
    # Create text splitter
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP
    )
    
    try:
        # Select appropriate loader based on file extension
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext == '.docx':
            loader = UnstructuredWordDocumentLoader(file_path)
        elif ext == '.pptx':
            loader = UnstructuredPowerPointLoader(file_path)
        elif ext == '.xlsx' or ext == '.xls':
            loader = UnstructuredExcelLoader(file_path)
        elif ext == '.csv':
            loader = CSVLoader(file_path)
        elif ext == '.json':
            loader = JSONLoader(file_path=file_path, jq_schema='.', text_content=False)
        elif ext == '.txt' or ext == '.md' or ext == '.py' or ext == '.js' or ext == '.html':
            loader = TextLoader(file_path, encoding='utf8')
        else:
            logger.warning(f"No specific loader for extension {ext}, trying TextLoader")
            loader = TextLoader(file_path, encoding='utf8')
            
        # Create a loader that applies the text splitter
        class SplittingLoader:
            def __init__(self, base_loader, splitter):
                self.base_loader = base_loader
                self.splitter = splitter
                
            def load(self):
                docs = self.base_loader.load()
                return self.splitter.split_documents(docs)
                
        return SplittingLoader(loader, text_splitter)
        
    except Exception as e:
        logger.error(f"Error creating loader for {file_path}: {e}", exc_info=True)
        return None