# SEO and indexing playbook

## Technical checks
- Homepage and important landing pages return expected status codes.
- HTTPS works and redirects are intentional.
- `robots.txt` does not accidentally block important content.
- XML sitemap is valid, reachable, and includes canonical indexable URLs.
- Important pages have correct canonical and index directives.
- Internal links make important pages discoverable.
- Titles, descriptions, headings, and rendered content accurately represent page intent.
- Duplicate, thin, broken, or orphan pages are identified.
- Mobile usability and page performance are checked with available evidence.
- Search Console or equivalent webmaster tool is configured when appropriate.

## Search Console manual fallback
If there is no authorized connection:
1. Ask the owner to open the relevant property in Google Search Console.
2. Inspect Pages/Indexing and URL Inspection for key URLs.
3. Review Performance by query, page, country, device, and date.
4. Record the exact date range and screenshots/export if useful.
5. Do not claim access or results until the user supplies evidence.

## Keyword map
Fields: query/topic, intent, audience, evidence, competitor/result pattern, target URL, title, H1, page outline, proof/assets needed, internal links, CTA, priority, risk.

## Core Web Vitals and page experience

Google uses Core Web Vitals as ranking factors. Check:

- **Largest Contentful Paint (LCP)**: Main content should load in <2.5s
- **First Input Delay (FID)** / **Interaction to Next Paint (INP)**: Page should respond to user input in <200ms
- **Cumulative Layout Shift (CLS)**: Visual stability — elements shouldn't shift unexpectedly (<0.1)

Tools:
- **PageSpeed Insights**: https://pagespeed.web.dev/ — free, gives CWV scores and recommendations
- **Chrome DevTools Lighthouse**: Built into Chrome, run on any page
- **Web Vitals extension**: Chrome extension for real-time monitoring

For indie products, common issues:
- Large unoptimized images (use WebP, lazy loading)
- Render-blocking JavaScript/CSS
- Third-party scripts slowing down the page
- Fonts causing layout shifts (use `font-display: swap`)

Fix critical issues first. Don't obsess over perfect scores — meaningful improvements matter more than chasing 100/100.

## E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness)

Google's E-E-A-T framework matters for ranking, especially for YMYL (Your Money or Your Life) topics. For indie products:

**Experience**: Show that you have real experience with the topic
- Write from personal experience: "I built this because..."
- Include screenshots, demos, case studies
- Share specific results and data

**Expertise**: Demonstrate technical knowledge
- Write detailed, accurate technical content
- Cite sources and provide evidence
- Show your work: code examples, implementation details

**Authoritativeness**: Build recognition as a credible source
- Get mentioned by other credible sites (backlinks, mentions)
- Build a presence on relevant platforms (GitHub, Dev.to, etc.)
- Earn reviews and testimonials

**Trustworthiness**: Be transparent and honest
- Clear about who you are and what you're selling
- Honest about limitations and pricing
- Privacy policy, terms of service, contact information
- HTTPS, secure checkout, data protection

For indie products without brand recognition:
- Focus on experience and expertise (you can demonstrate these immediately)
- Build authority over time through consistent, quality content
- Earn trust through transparency and honesty

## Internal linking strategy

Internal links help Google discover and understand your pages. They also distribute link equity throughout your site.

**Principles**:
- **Link from high-authority pages to important pages**: Homepage, popular blog posts → key landing pages
- **Use descriptive anchor text**: "See our pricing" not "click here"
- **Create topic clusters**: Hub page (e.g., "SEO Guide") → related pages (technical SEO, keywords, etc.)
- **Fix orphan pages**: Every important page should have at least 2–3 internal links pointing to it
- **Use breadcrumbs**: Helps users and Google understand site structure

**Implementation**:
- Audit your site: which pages have no internal links pointing to them?
- Add links from your homepage to key landing pages
- Link related blog posts to each other
- Create "related posts" or "see also" sections
- Use navigation menus strategically (don't overload, but include important pages)

## Structured data (schema markup)

Schema markup helps search engines understand your content and can earn you rich results (star ratings, FAQs, how-tos in search results).

**Common schema types for indie products**:

**SoftwareApplication**:
```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "Your Product",
  "operatingSystem": "Web",
  "applicationCategory": "BusinessApplication",
  "description": "One-sentence description",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  }
}
```

**FAQPage**: For frequently asked questions
```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is your product?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "Your product is..."
      }
    }
  ]
}
```

**HowTo**: For tutorials and guides
**Organization**: For company info, logo, social profiles
**Review / AggregateRating**: If you have genuine reviews
**BreadcrumbList**: For navigation structure

**Implementation**:
- Use Google's Structured Data Markup Helper to generate schema
- Test with Google's Rich Results Test: https://search.google.com/test/rich-results
- Don't overdo it — add schema where it genuinely clarifies content
- Validate after implementation

## Quality rules
- Do not promise indexing or rankings.
- `site:` search is only a rough diagnostic, not a definitive index report.
- Do not mass-create thin pages just to target keywords.
- Every suggested page must have a distinct user intent and original value.
- Validate search volume and difficulty using a named source; if unavailable, mark qualitative.
