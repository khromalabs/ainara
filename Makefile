.PHONY: setup install

install:
	pip install -r requirements.txt

setup: install
	python bin/setup_nltk.py

all: install setup
