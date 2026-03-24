# Beer Recommender - House of Beers

A personalized beer recommendation system for House of Beers (Shopify craft beer store). Analyzes Untappd user profiles OR Shopify order history to recommend beers from the store's inventory.

## Architecture

- **Backend**: Django + Django REST Framework
- **Task Queue**: Celery with Redis broker
- **Database**: PostgreSQL (production) / SQLite (dev)
- **Hosting**: Dokku at `recommendation.houseofbeers.nl`

## Key Components

### API Endpoints (`recommendations/views.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recommendations/` | POST | Get personalized recommendations (async for new users). Accepts `username` (Untappd) OR `email` (Shopify customer) |
| `/api/tasks/<task_id>/` | GET | Poll async task status |
| `/api/profile/<identifier>/` | GET | Get user taste profile for visualizations. Use `?type=shopify` for email profiles |
| `/api/beers/` | GET | List beers with filtering |
| `/api/styles/` | GET | List available style categories |
| `/api/countries/` | GET | List available countries |
| `/api/sync/status/` | GET | Check Shopify sync status |
| `/api/sync/trigger/` | POST | Manually trigger Shopify sync |

### Services

- **`shopify_sync.py`** - Syncs beer catalog from Shopify GraphQL API
- **`shopify_customer.py`** - Fetches customer order history from Shopify to build taste profiles
- **`untappd_scraper.py`** - Scrapes user profiles from Untappd (public data, multi-sort sampling)
- **`recommendation_engine.py`** - Scores and ranks beers based on user preferences
- **`style_mapper.py`** - Maps detailed beer styles to categories

### Celery Tasks (`recommendations/tasks.py`)

- `sync_shopify_catalog` - Nightly catalog sync (scheduled via django-celery-beat)
- `refresh_user_profile` - Background profile refresh
- `generate_recommendations_task` - Async recommendation generation (Untappd)
- `generate_recommendations_email_task` - Async recommendation generation (Shopify email)

### Frontend Widget (`shopify_widget.html`)

Self-contained HTML/CSS/JS widget for embedding in Shopify pages (Dutch language):
- Toggle between Email (Shopify) and Untappd input modes
- Filters: price, style, count
- Handles async responses with polling
- Displays: taste profile radar chart, recommendations, discovery picks, tried beers
- Share functionality (works for both profile types)
- Add to cart integration with Shopify Ajax Cart API

## Profile Types

### 1. Untappd Profiles
- User provides their Untappd username
- Scraper fetches beer history using 10 different sort parameters for comprehensive sampling:
  - `date`, `date_asc` - Recent and oldest beers
  - `highest_rated_you`, `lowest_rated_you` - User's ratings
  - `highest_rated`, `lowest_rated` - Global ratings
  - `highest_abv`, `lowest_abv` - ABV preferences
  - `checkin`, `checkin_desc` - Check-in popularity
- Builds taste profile from styles, breweries, ABV, ratings
- Detects private profiles and shows appropriate error message

### 2. Shopify Email Profiles
- User provides their email address
- System fetches order history from Shopify GraphQL API
- Builds taste profile from purchased beers (styles, ABV, price range)
- No ratings available, but purchase frequency indicates preference

### Cached Profiles (`CachedUserProfile` model)
- `profile_type`: "untappd" or "shopify"
- Profiles cached for 24 hours
- Unique constraints per profile type

## Radar Chart (Taste Wheel)

Dynamic radar chart showing user's top beer style preferences:
- Shows only styles the user has actually tried (max 8 axes)
- Requires minimum 3 styles for proper visualization
- Scores based on count (70%) + rating bonus (30%)
- Styles sorted by combined score to show most relevant ones

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

## Completed Features

- [x] Email-based recommendations from Shopify order history
- [x] Multi-sort Untappd scraping for better taste profiles (10 sort variations)
- [x] Dynamic radar chart (only shows tried styles, max 8 axes)
- [x] Dutch language widget
- [x] Share functionality for both profile types
- [x] Add to cart integration with Shopify Ajax Cart API
- [x] Private Untappd profile detection with helpful error messages
- [x] Responsive widget design

## Future Enhancements

- Save favorite beers
- Beer comparison feature
- Integration with Shopify customer accounts
- Webhook for automatic profile refresh on new orders
