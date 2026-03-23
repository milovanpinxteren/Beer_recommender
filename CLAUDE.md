# Beer Recommender - House of Beers

A personalized beer recommendation system for House of Beers (Shopify craft beer store). Analyzes Untappd user profiles to recommend beers from the store's inventory.

## Architecture

- **Backend**: Django + Django REST Framework
- **Task Queue**: Celery with Redis broker
- **Database**: PostgreSQL (production) / SQLite (dev)
- **Hosting**: Dokku at `recommendation.houseofbeers.nl`

## Key Components

### API Endpoints (`recommendations/views.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recommendations/` | POST | Get personalized recommendations (async for new users) |
| `/api/tasks/<task_id>/` | GET | Poll async task status |
| `/api/profile/<username>/` | GET | Get user taste profile for visualizations |
| `/api/beers/` | GET | List beers with filtering |
| `/api/styles/` | GET | List available style categories |
| `/api/countries/` | GET | List available countries |
| `/api/sync/status/` | GET | Check Shopify sync status |
| `/api/sync/trigger/` | POST | Manually trigger Shopify sync |

### Services

- **`shopify_sync.py`** - Syncs beer catalog from Shopify GraphQL API
- **`untappd_scraper.py`** - Scrapes user profiles from Untappd (public data)
- **`recommendation_engine.py`** - Scores and ranks beers based on user preferences
- **`style_mapper.py`** - Maps detailed beer styles to categories

### Celery Tasks (`recommendations/tasks.py`)

- `sync_shopify_catalog` - Nightly catalog sync (scheduled via django-celery-beat)
- `refresh_user_profile` - Background profile refresh
- `generate_recommendations_task` - Async recommendation generation

### Frontend Widget (`shopify_widget.html`)

Self-contained HTML/CSS/JS widget for embedding in Shopify pages:
- Username input with filters (price, style, count)
- Handles async responses with polling
- Displays profile summary, recommendations, discovery picks, tried beers

## Async Flow (to avoid timeouts)

1. User requests recommendations via widget
2. API checks if profile is cached (< 24h old)
3. **If cached**: Returns recommendations immediately (sync)
4. **If not cached**:
   - Starts Celery task, returns `task_id` with HTTP 202
   - Widget polls `/api/tasks/<task_id>/` every 2 seconds
   - Worker scrapes Untappd profile (can take 30-60 seconds)
   - When complete, widget displays results

## Environment Variables (Dokku)

```
SECRET_KEY=<django-secret>
DEBUG=False
ALLOWED_HOSTS=recommendation.houseofbeers.nl
CSRF_TRUSTED_ORIGINS=https://recommendation.houseofbeers.nl
CORS_ALLOWED_ORIGINS=https://houseofbeers.nl,https://www.houseofbeers.nl
DATABASE_URL=postgres://...
REDIS_URL=redis://...
SHOPIFY_DOMAIN=7c70bf.myshopify.com
SHOPIFY_ACCESS_TOKEN=shpat_...
```

## Deployment

```bash
git push dokku main
```

Procfile runs:
- `web`: gunicorn
- `worker`: celery worker
- `beat`: celery beat scheduler
- `release`: migrate + collectstatic

## Admin

Django admin at `/admin/` includes:
- Beer catalog management
- Manual Shopify sync button
- Cached user profiles
- Celery periodic tasks (for scheduling)

## Next Steps

### 1. Improve Widget Template
- Better styling to match House of Beers branding
- Responsive improvements
- Loading animations
- Error handling UX

### 2. Add to Cart Functionality
- Integrate with Shopify's Ajax Cart API
- Add "Add to Cart" button on each beer card
- Support quantity selection
- Show cart feedback (drawer/notification)

Example Shopify Cart API integration:
```javascript
async function addToCart(variantId, quantity = 1) {
  const response = await fetch('/cart/add.js', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: variantId,
      quantity: quantity
    })
  });
  return response.json();
}
```

Note: Need to sync Shopify variant IDs (not just product IDs) to enable cart functionality.

### 3. Future Enhancements
- Email capture for recommendations
- Save favorite beers
- Share recommendations
- Beer comparison feature
- Integration with Shopify customer accounts
