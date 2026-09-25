#!/bin/bash
input=$(cat)

if [ -d "docs/impact-maps" ]; then
  latest_map=$(ls -t docs/impact-maps/*.md 2>/dev/null | head -1)
  if [ -n "$latest_map" ]; then
    if ! grep -q "APPROVED" "$latest_map" 2>/dev/null; then
      echo '{
        "followup_message": "An MCO impact map was created but not yet approved. Please ask the human to review docs/impact-maps/ before proceeding. Remember: this is a monorepo — verify all 5 components were analyzed."
      }'
      exit 0
    fi
  fi
fi

echo '{}'
exit 0
