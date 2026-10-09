# AI search optimization playbook (GEO / AEO)

## Why this matters in 2026

Users increasingly get product recommendations from ChatGPT, Perplexity, Google AI Overviews, Claude, and other AI systems. Traditional SEO is necessary but not sufficient. You need to optimize for how LLMs retrieve and cite information.

## How LLMs choose what to cite

LLMs don't "rank" pages the way Google does. They retrieve information based on:

1. **Authority signals**: Your product is mentioned by reputable third parties (tech blogs, review sites, comparison articles, documentation aggregators)
2. **Structured information**: Clear, factual, well-organized content that's easy to extract
3. **Recency and relevance**: Recent mentions, up-to-date documentation, active development
4. **Consistency**: The same facts appear across multiple independent sources
5. **Direct answers**: Content that directly answers common questions about your product category

## Optimization checklist

### 1. Build citation-worthy content

Create content that LLMs can easily extract and cite:

- **Clear product descriptions**: One-sentence positioning, core features, pricing, target audience — stated plainly on your homepage and About page
- **FAQ pages**: Answer the exact questions users ask (e.g., "What is [product]?", "How does [product] compare to [competitor]?", "Is [product] free?")
- **Comparison content**: "[Your product] vs [competitor]" pages with factual, balanced comparisons
- **Use cases and tutorials**: Step-by-step guides that demonstrate real value
- **Changelog / What's new**: Shows active development and recent improvements
- **Pricing page**: Clear, machine-readable pricing information

### 2. Earn third-party mentions

LLMs trust independent sources more than your own website. Prioritize:

- **Tech blog coverage**: Get reviewed or mentioned by relevant tech blogs (free or paid)
- **Comparison articles**: "Best [category] tools" articles where your product is included
- **Tutorial mentions**: Tutorials that use your product as an example
- **Directory listings**: Reputable directories (AlternativeTo, G2, Capterra, Product Hunt)
- **Integration partnerships**: If you integrate with known platforms, get listed in their directories
- **Open-source presence**: GitHub repos with good documentation get cited
- **Community mentions**: Reddit threads, Hacker News discussions, Stack Overflow answers where your product is genuinely recommended

### 3. Structured data for AI consumption

Use schema.org markup to make your content machine-readable:

- **SoftwareApplication**: Name, description, operatingSystem, applicationCategory, offer (pricing)
- **FAQPage**: Common questions and answers
- **HowTo**: Step-by-step guides
- **Organization**: Company info, logo, social profiles
- **Review / AggregateRating**: If you have genuine reviews
- **BreadcrumbList**: Helps AI understand site structure

Don't overdo it. Add schema where it genuinely clarifies content, not just for the sake of it.

### 4. Optimize for specific AI platforms

**ChatGPT / GPT-4**:
- ChatGPT browse the web (when enabled) and use Bing
- It cites sources with links when it retrieves real-time info
- Clear, factual content with recent updates is preferred
- Mention your product in contexts where users ask for recommendations

**Perplexity**:
- Aggressively cites sources with inline links
- Values recent, authoritative sources
- Clear product pages with pricing and features get cited
- Comparison content performs well

**Google AI Overviews**:
- Appears at the top of Google search results
- Favors established, authoritative sites
- Structured data helps Google understand your content
- Being in the top organic results increases citation chance

**Claude**:
- Can browse the web (with tools enabled)
- Values clear, well-organized documentation
- Factual, balanced content is preferred over marketing hype

### 5. Monitor AI citations

You can't directly track when an AI cites you, but you can:

- **Search for your product** in ChatGPT, Perplexity, Claude and see if/when it's mentioned
- **Monitor referral traffic** from AI platforms (check UTM parameters or referrer headers — though many AI systems don't pass referrer info)
- **Track brand mentions** in AI-generated content by asking users or searching
- **Monitor "mentioned in" sections** in tools like Perplexity (it shows sources)

### 6. Avoid these mistakes

- **Don't stuff keywords** for AI — LLMs understand natural language
- **Don't fabricate reviews or mentions** — AI systems cross-reference sources
- **Don't ignore traditional SEO** — AI citation builds on top of good SEO, not replaces it
- **Don't expect immediate results** — AI training data and retrieval indexes update on their own schedules
- **Don't game the system** — focus on genuine value and legitimate mentions

## Measurement

Track:
- AI platform mentions (manual checks, monthly)
- Referral traffic from AI sources (if detectable)
- Third-party mentions and reviews (leading indicator)
- Structured data validation (use Google's Rich Results Test or similar)
- Brand search volume (if people hear about you from AI, they'll search)

## When to prioritize this

- Your product is in a category where users ask AI for recommendations (SaaS, developer tools, productivity, etc.)
- You've already covered basic SEO and directory listings
- You have content that's being created anyway (blog, docs, changelog) — optimize it for AI citation as a bonus
- You notice competitors being cited by AI and you're not

## When to deprioritize

- Your product is very niche with a small audience that doesn't use AI for recommendations
- You haven't done basic SEO yet (fix the foundation first)
- You're seeing good results from traditional channels and have limited bandwidth
