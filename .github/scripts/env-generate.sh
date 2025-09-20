#!/bin/sh

# This script finds all .env.example files in the current directory and its subdirectories,
# and creates a corresponding .env file if it does not already exist.
find . -type f -name '.env.example' -print0 | while IFS= read -r -d '' src; do dst="${src%.env.example}.env"; [ -e "$dst" ] || /bin/cp "$src" "$dst"; done