# Cloudflare R2 Setup Guide

This guide explains how to set up Cloudflare R2 for Django media file storage in your High School Backend application.

## What is Cloudflare R2?

Cloudflare R2 is an S3-compatible object storage service with:
- **No egress fees** - Free data transfer out
- **Competitive pricing** - $0.015/GB stored per month
- **S3 API compatibility** - Works with existing S3 tools
- **Global distribution** - Fast access worldwide
- **Custom domains** - Use your own domain for media URLs

## Prerequisites

1. A Cloudflare account (create at https://dash.cloudflare.com/)
2. Python packages already installed:
   - `django-storages==1.14.4`
   - `boto3==1.35.67`

## Step 1: Create R2 Bucket

1. Log in to your Cloudflare dashboard
2. Navigate to **R2** in the left sidebar
3. Click **Create bucket**
4. Enter a bucket name (e.g., `highschool-media`)
5. Choose a location hint (optional)
6. Click **Create bucket**

## Step 2: Create API Token

1. In the R2 dashboard, click **Manage R2 API Tokens**
2. Click **Create API Token**
3. Give it a name (e.g., `Django Backend Token`)
4. Set permissions:
   - **Object Read & Write** for your bucket
5. Click **Create API Token**
6. **Save these credentials immediately** (you won't see them again):
   - Access Key ID
   - Secret Access Key
   - Endpoint URL (format: `https://<account-id>.r2.cloudflarestorage.com`)

## Step 3: Configure Public Access (Optional)

If you want files to be publicly accessible via R2's default domain:

1. Go to your bucket settings
2. Click on **Settings** tab
3. Under **Public access**, click **Allow Access**
4. Confirm the action

**Note:** For production, it's recommended to use a custom domain instead.

## Step 4: Set Up Custom Domain (Recommended)

Using a custom domain provides better branding and control:

1. In your bucket settings, go to **Settings** > **Custom Domains**
2. Click **Connect Domain**
3. Enter your domain (e.g., `media.yourschool.com` or `cdn.yourschool.com`)
4. Follow the DNS configuration instructions
5. Add the CNAME record to your domain's DNS:
   ```
   CNAME  media  <bucket-name>.<account-id>.r2.cloudflarestorage.com
   ```
6. Wait for DNS propagation (can take up to 48 hours, usually much faster)

## Step 5: Configure Django Environment Variables

Add these environment variables to your production environment:

### For Railway, Render, or similar platforms:

```bash
R2_BUCKET=your-bucket-name
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key
R2_S3_ENDPOINT=https://your-account-id.r2.cloudflarestorage.com
R2_CUSTOM_DOMAIN=media.yourschool.com  # Optional, if using custom domain
```

### For local .env file (development):

Development uses local file storage by default (when `DEBUG=True`), so you don't need R2 credentials locally unless testing production settings.

## Step 6: Test the Setup

### Test file upload in Django shell:

```python
python manage.py shell

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# Test upload
content = ContentFile(b"Test content")
path = default_storage.save("test.txt", content)
print(f"File saved to: {path}")

# Test URL generation
url = default_storage.url(path)
print(f"File URL: {url}")

# Test file exists
exists = default_storage.exists(path)
print(f"File exists: {exists}")

# Clean up
default_storage.delete(path)
print("Test file deleted")
```

### Test via API endpoint:

If you have image upload endpoints (e.g., user profile photos), test them:

```bash
# Upload a file
curl -X POST http://localhost:8000/api/users/profile/photo/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "photo=@/path/to/image.jpg"

# Check the response for the R2 URL
```

## Step 7: Migrate Existing Media Files (If Any)

If you have existing media files in local storage or another service:

### Option 1: Use AWS CLI (or rclone)

1. Install AWS CLI:
   ```bash
   pip install awscli
   ```

2. Configure AWS CLI for R2:
   ```bash
   aws configure --profile r2
   # Enter your R2 credentials when prompted
   ```

3. Sync files:
   ```bash
   aws s3 sync ./media/ s3://your-bucket-name/ \
     --endpoint-url https://your-account-id.r2.cloudflarestorage.com \
     --profile r2
   ```

### Option 2: Django Management Command

Create a custom management command:

```python
# api/management/commands/migrate_to_r2.py
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage
from django.conf import settings
import os

class Command(BaseCommand):
    help = 'Migrate media files to R2'

    def handle(self, *args, **options):
        media_root = settings.MEDIA_ROOT
        
        for root, dirs, files in os.walk(media_root):
            for filename in files:
                local_path = os.path.join(root, filename)
                relative_path = os.path.relpath(local_path, media_root)
                
                with open(local_path, 'rb') as f:
                    default_storage.save(relative_path, f)
                    self.stdout.write(f"Uploaded: {relative_path}")
```

Then run:
```bash
python manage.py migrate_to_r2
```

## Configuration Details

### Storage Settings Explained

The configuration in `api/settings/storage.py`:

```python
STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": R2_BUCKET,
            "access_key": R2_ACCESS_KEY_ID,
            "secret_key": R2_SECRET_ACCESS_KEY,
            "endpoint_url": R2_S3_ENDPOINT,
            "region_name": "auto",  # R2 requires "auto"
            "signature_version": "s3v4",  # S3v4 signature
            "addressing_style": "path",  # Path-style URLs
            "querystring_auth": False,  # No signed URLs by default
            "default_acl": None,  # R2 doesn't use ACLs
            "file_overwrite": False,  # Keep multiple versions
            "object_parameters": {
                "CacheControl": "public, max-age=86400",  # 24hr cache
            },
        },
    },
}
```

### Key Configuration Options:

- **region_name**: Must be `"auto"` for R2
- **querystring_auth**: Set to `False` for public files, `True` for private/signed URLs
- **file_overwrite**: Set to `False` to prevent accidental overwrites
- **CacheControl**: Optimizes CDN caching (24 hours = 86400 seconds)

## CORS Configuration (If Accessing from Frontend)

If your frontend directly uploads to R2 or accesses images cross-origin:

1. In R2 bucket settings, go to **Settings** > **CORS policy**
2. Add CORS rules:

```json
[
  {
    "AllowedOrigins": ["https://yourfrontend.com"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

## Security Best Practices

1. **Separate Buckets**: Use different buckets for staging/production
2. **Limit Token Permissions**: Only grant necessary permissions to API tokens
3. **Rotate Keys**: Regularly rotate your R2 access keys
4. **Use Custom Domain**: Better control and can enable Cloudflare WAF/DDoS protection
5. **Enable Versioning**: Keep file versions for recovery
6. **Monitor Usage**: Check R2 analytics regularly for unusual activity

## Troubleshooting

### Files not uploading:

1. Check environment variables are set correctly
2. Verify bucket permissions
3. Check endpoint URL format
4. Review Django logs for boto3 errors

### Files uploading but not accessible:

1. Verify bucket public access is enabled (if not using custom domain)
2. Check CORS configuration
3. Verify custom domain DNS is properly configured
4. Check `querystring_auth` setting

### Slow uploads:

1. Consider increasing chunk size for large files
2. Use custom domain with Cloudflare CDN
3. Check network connectivity to R2 endpoint

### Getting 403 errors:

1. Verify API token has correct permissions
2. Check token hasn't expired
3. Verify endpoint URL matches your account
4. Check bucket name is correct

## Cost Estimation

Cloudflare R2 pricing (as of 2024):
- **Storage**: $0.015/GB per month
- **Class A Operations** (write, list): $4.50/million
- **Class B Operations** (read): $0.36/million
- **Data Transfer**: **FREE** (no egress fees!)

Example monthly costs:
- 10GB storage + 100K uploads + 1M downloads = ~$0.60/month
- 100GB storage + 1M uploads + 10M downloads = ~$6.00/month

## Additional Resources

- [Cloudflare R2 Documentation](https://developers.cloudflare.com/r2/)
- [django-storages Documentation](https://django-storages.readthedocs.io/)
- [boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)

## Support

For issues specific to this implementation, check:
1. Django logs in `logs/` directory
2. Railway/deployment platform logs
3. Cloudflare R2 analytics dashboard
