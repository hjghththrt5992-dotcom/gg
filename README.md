# gg

A minimal search engine MVP.

## Features

- Crawl a webpage
- Build a simple in-memory index
- Search via HTTP

## Install

```bash
npm install
```

## Run

```bash
npm start
```

## Usage

### Crawl a page

```bash
curl -X POST http://localhost:3000/crawl -H "Content-Type: application/json" -d '{"url":"https://example.com"}'
```

### Search

Open in browser:

http://localhost:3000/search?q=example

## Notes

This is a toy search engine. No ranking, no persistence, no distributed crawling.
