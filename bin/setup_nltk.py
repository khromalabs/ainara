import os
import sys
from pathlib import Path

# Configure NLTK paths before importing
nltk_data_dir = os.path.join('orakle', 'skills', 'sentiment', 'nltk_data')
nltk_data_path = str(Path(nltk_data_dir).absolute())
os.environ['NLTK_DATA'] = nltk_data_path

# Now import NLTK and TextBlob
import nltk
nltk.data.path = [nltk_data_path]  # Override default paths
from textblob.download_corpora import download_lite

def setup_nltk():
    """Download NLTK and TextBlob data to project-local directory"""
    os.makedirs(nltk_data_path, exist_ok=True)
    print(f"Downloading NLTK data to: {nltk_data_path}")
    
    # Download required resources
    resources = ['brown', 'punkt', 'averaged_perceptron_tagger', 'wordnet']
    for resource in resources:
        nltk.download(resource, download_dir=nltk_data_path, quiet=True)
        print(f"Downloaded {resource}")
    
    # Download TextBlob corpora
    print("Downloading TextBlob corpora...")
    import tempfile
    old_dir = tempfile.gettempdir()
    tempfile.tempdir = nltk_data_path
    download_lite()
    tempfile.tempdir = old_dir
    
    print("Setup complete!")

if __name__ == '__main__':
    setup_nltk()
