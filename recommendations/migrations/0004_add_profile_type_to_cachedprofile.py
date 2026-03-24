# Generated manually for profile_type field on CachedUserProfile

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recommendations', '0003_add_variant_id_to_beer'),
    ]

    operations = [
        # Add profile_type field with default 'untappd'
        migrations.AddField(
            model_name='cacheduserprofile',
            name='profile_type',
            field=models.CharField(
                choices=[('untappd', 'Untappd'), ('shopify', 'Shopify Email')],
                db_index=True,
                default='untappd',
                max_length=20,
            ),
        ),
        # Add index to email field
        migrations.AlterField(
            model_name='cacheduserprofile',
            name='email',
            field=models.EmailField(blank=True, db_index=True, max_length=254, null=True),
        ),
        # Remove unique constraint on untappd_username (we'll add conditional ones)
        migrations.AlterField(
            model_name='cacheduserprofile',
            name='untappd_username',
            field=models.CharField(db_index=True, max_length=100),
        ),
        # Add unique constraints for each profile type
        migrations.AddConstraint(
            model_name='cacheduserprofile',
            constraint=models.UniqueConstraint(
                condition=models.Q(profile_type='untappd'),
                fields=['untappd_username'],
                name='unique_untappd_username',
            ),
        ),
        migrations.AddConstraint(
            model_name='cacheduserprofile',
            constraint=models.UniqueConstraint(
                condition=models.Q(profile_type='shopify'),
                fields=['email'],
                name='unique_shopify_email',
            ),
        ),
    ]
