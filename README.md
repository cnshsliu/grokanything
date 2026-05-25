# grokanything

<p align="center">
  <img src="./grokanything-logo.webp" alt="grokanything logo" width="200">
</p>

Send questions or file content to Grok via Chrome DevTools Protocol (CDP).

## Requirements

- Chrome running with `--remote-debugging-port=9222`
- A grok.com tab open in Chrome

## Usage

```bash
# Ask a question
grokanything "What is the capital of France?"

# Send a file
grokanything ~/Documents/my-code.py

# Help
grokanything --help
```

## Install

```bash
# Clone and symlink to your PATH
git clone https://github.com/liukehong/grokanything.git ~/dev/grokanything
ln -s ~/dev/grokanything/grokanything ~/bin/grokanything
```

## Features

- Reuses existing Grok tab (no focus stealing)
- New conversation per query
- Waits for response and captures full text
- Waits for previous generation to complete before submitting
- Supports file input (reads file content and sends to Grok)
