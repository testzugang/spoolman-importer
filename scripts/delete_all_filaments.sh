#!/bin/bash
# Deletes all filaments from Spoolman.
#
# Usage:
#   ./delete_all_filaments.sh [SPOOLMAN_URL]
#
# Example:
#   ./delete_all_filaments.sh http://localhost:7912

SPOOLMAN_URL=${1:-http://localhost:7912}

# Get all filament IDs
IDS=$(curl -s -X GET "$SPOOLMAN_URL/api/v1/filament" | jq -r '.[].id')

if [ -z "$IDS" ]; then
  echo "No filaments found."
  exit 0
fi

echo "This will delete all filaments. Are you sure? (y/n)"
read -r confirmation
if [ "$confirmation" != "y" ]; then
  echo "Aborting."
  exit 0
fi

# Loop through IDs and delete each filament
for id in $IDS; do
  echo "Deleting filament with ID: $id"
  curl -s -X DELETE "$SPOOLMAN_URL/api/v1/filament/$id"
done

echo "All filaments have been deleted."
