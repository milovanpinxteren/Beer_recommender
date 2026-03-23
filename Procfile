web: gunicorn beer_recommender.wsgi --log-file -
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
