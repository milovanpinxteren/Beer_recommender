web: gunicorn beer_recommender.wsgi --log-file -
worker: celery -A beer_recommender worker --loglevel=info
beat: celery -A beer_recommender beat --loglevel=info
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
