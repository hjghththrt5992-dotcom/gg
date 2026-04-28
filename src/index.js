const express = require('express');
const fetch = require('node-fetch');
const cheerio = require('cheerio');

const app = express();
app.use(express.json());

// simple in-memory index
const index = {};

function addToIndex(url, text) {
  const words = text.toLowerCase().split(/\W+/);
  words.forEach(word => {
    if (!word) return;
    if (!index[word]) index[word] = new Set();
    index[word].add(url);
  });
}

app.post('/crawl', async (req, res) => {
  const { url } = req.body;
  try {
    const response = await fetch(url);
    const html = await response.text();
    const $ = cheerio.load(html);
    const text = $('body').text();

    addToIndex(url, text);

    res.json({ message: 'Indexed', url });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get('/search', (req, res) => {
  const { q } = req.query;
  if (!q) return res.json([]);

  const words = q.toLowerCase().split(/\W+/);
  let results = null;

  words.forEach(word => {
    const urls = index[word] || new Set();
    if (results === null) {
      results = new Set(urls);
    } else {
      results = new Set([...results].filter(x => urls.has(x)));
    }
  });

  res.json(Array.from(results || []));
});

app.get('/', (req, res) => {
  res.send(`
    <h1>GG Search Engine</h1>
    <form action="/search">
      <input name="q" placeholder="Search..." />
      <button type="submit">Search</button>
    </form>
  `);
});

app.listen(3000, () => {
  console.log('Server running on http://localhost:3000');
});
