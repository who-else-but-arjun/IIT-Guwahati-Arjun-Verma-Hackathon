#!/bin/bash
set -eu

# The official Mongo image runs this only for a brand-new data directory.
# Existing mongo_data volumes are left untouched.
mongorestore \
  --host=localhost \
  --port=27017 \
  --gzip \
  --archive=/seed/financial_nlp.archive.gz \
  --nsInclude='financial_nlp.*'
