#!/bin/bash
# Deletes all spools from Spoolman.
#
# Usage:
#   ./delete_all_spools.sh [SPOOLMAN_URL]
#
# Example:
#   ./delete_all_spools.sh http://localhost:7912

SPOOLMAN_URL=${1:-http://localhost:7912}

# Get all spool IDs
IDS=$(curl -s -X GET "$SPOOLMAN_URL/api/v1/spool" | jq -r '.[].id')

if [ -z "$IDS" ]; then
  echo "No spools found."
  exit 0
fi

echo "This will delete all spools. Are you sure? (y/n)"
read -r confirmation
if [ "$confirmation" != "y" ]; then
  echo "Aborting."
  exit 0
fi

# Loop through IDs and delete each spool
for id in $IDS; do
  echo "Deleting spool with ID: $id"
  curl -s -X DELETE "$SPOOLMAN_URL/api/v1/spool/$id"
done

echo "All spools have been deleted."
