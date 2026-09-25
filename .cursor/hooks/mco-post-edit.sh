#!/bin/bash
input=$(cat)
file=$(echo "$input" | jq -r '.filePath // empty')

if [ -z "$file" ]; then
  echo '{}'
  exit 0
fi

context=""

# Remind about vendor if go.mod was touched
if [[ $file == "go.mod" ]] || [[ $file == "go.sum" ]]; then
  context="go.mod was modified — remember to run 'make deps' to update vendor/."
fi

# Remind about bundle if API types were touched
if [[ $file == operators/multiclusterobservability/api/* ]]; then
  context="API types were modified — remember to run 'make bundle' and commit the generated changes."
fi

# Remind about fmt.Print ban
if [[ $file == operators/* ]] || [[ $file == collectors/* ]] || [[ $file == proxy/* ]] || [[ $file == loaders/* ]]; then
  if [[ $file != *"_test.go" ]]; then
    if grep -q 'fmt\.Print' "$file" 2>/dev/null; then
      context="WARNING: fmt.Print* detected in non-test code. faillint will reject this — use structured logging instead."
    fi
  fi
fi

if [ -n "$context" ]; then
  echo "{\"additional_context\": \"$context\"}"
else
  echo '{}'
fi
exit 0
