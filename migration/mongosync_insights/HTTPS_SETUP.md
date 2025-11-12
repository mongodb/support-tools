# HTTPS Setup Guide for Mongosync Insights

This guide explains how to enable HTTPS/SSL for Mongosync Insights to secure your deployment.

## Prerequisites

**Python 3.10+** is required. All commands in this guide use `python3` to ensure you're running Python 3.x.

## Quick Reference

| Setup Type | Best For | Complexity | Security |
|------------|----------|------------|----------|
| HTTP (Default) | Local dev, testing | ⭐ Easy | ⚠️ Low |
| Direct Flask SSL | Small deployments | ⭐⭐ Medium | ✅ Good |
| Reverse Proxy | Production | ⭐⭐⭐ Advanced | ✅ Excellent |

## Why Use HTTPS?

Mongosync Insights handles sensitive data that should be protected in transit:

### 🔐 **Credentials Protection**
The application transmits MongoDB connection strings containing usernames and passwords. Without HTTPS, these credentials are sent as plaintext over the network, making them vulnerable to interception by anyone monitoring network traffic.

### 📊 **Database Metrics Privacy**
Mongosync Insights displays detailed metrics about your database infrastructure, including collection names, performance characteristics, and sizing information. This data could reveal sensitive details about your application architecture to unauthorized parties.

### 🛡️ **Security Features Require HTTPS**
Several built-in security features only function properly with HTTPS:
- **Secure session cookies** prevent session hijacking attacks
- **HSTS headers** protect against protocol downgrade attacks
- **Content Security Policy** guards against XSS attacks

Without HTTPS, these protections are either disabled or ineffective.

### ✅ **Best Practice**
For any production deployment, especially those accessible over the internet or untrusted networks, HTTPS is industry standard and essential for maintaining data confidentiality and integrity.

---

**When HTTP is acceptable:**
- Local development on `localhost`
- Testing environments on isolated networks
- Internal deployments with network-level security controls

**When HTTPS is required:**
- Production deployments
- Internet-facing applications
- Access over untrusted networks (public WiFi, VPNs, etc.)
- Compliance requirements (SOC 2, PCI DSS, HIPAA, etc.)

---

## Table of Contents

1. [Why Use HTTPS?](#why-use-https)
2. [Default Setup (HTTP)](#default-setup-http)
3. [Option A: Direct Flask SSL](#option-a-direct-flask-ssl)
4. [Option B: Reverse Proxy (Recommended for Production)](#option-b-reverse-proxy-recommended-for-production)
5. [Environment Variables Reference](#environment-variables-reference)
6. [Firewall Configuration](#firewall-configuration)
7. [Verify HTTPS Setup](#verify-https-setup)
8. [Troubleshooting](#troubleshooting)

---

## Default Setup (HTTP)

By default, Mongosync Insights runs on HTTP without SSL encryption. This is suitable for:
- Local development
- Testing environments
- Internal networks with other security measures

**No configuration needed** - the application runs on HTTP by default.

```bash
# Default behavior
python3 mongosync_insights.py

# Access at: http://localhost:3030
```

⚠️ **Warning**: HTTP is not secure for production deployments exposed to the internet.

---

## Option A: Direct Flask SSL

Enable HTTPS directly in the Flask application using SSL certificates.

### When to Use This Option

- Simple deployments without a reverse proxy
- Testing SSL/HTTPS functionality
- Small-scale production environments

### Prerequisites

- SSL certificate and private key files
- Access to bind to port 443 (requires root/sudo or port forwarding)

### Step 1: Obtain SSL Certificates

#### Using Let's Encrypt (Free)

```bash
# Install certbot
# Ubuntu/Debian:
sudo apt-get update
sudo apt-get install certbot

# CentOS/RHEL:
sudo yum install certbot

# macOS:
brew install certbot

# Generate certificates
sudo certbot certonly --standalone -d your-domain.com

# Certificates will be created at:
# /etc/letsencrypt/live/your-domain.com/fullchain.pem (certificate)
# /etc/letsencrypt/live/your-domain.com/privkey.pem (private key)
```

#### Using Self-Signed Certificates (Testing Only)

```bash
# Create self-signed certificate for testing
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout key.pem \
  -out cert.pem \
  -days 365 \
  -subj "/CN=localhost"

# This creates:
# cert.pem (certificate)
# key.pem (private key)
```

⚠️ **Warning**: Self-signed certificates will show browser warnings. Use only for testing.

### Step 2: Configure Environment Variables

Create or update your environment configuration:

```bash
# Enable SSL
export MI_SSL_ENABLED=true

# Provide certificate paths
export MI_SSL_CERT=/etc/letsencrypt/live/your-domain.com/fullchain.pem
export MI_SSL_KEY=/etc/letsencrypt/live/your-domain.com/privkey.pem

# Optional: Use standard HTTPS port (requires root/sudo)
export MI_PORT=443

# Enable secure cookies
export MI_SECURE_COOKIES=true
```

Or create a `.env` file:

```bash
MI_SSL_ENABLED=true
MI_SSL_CERT=/etc/letsencrypt/live/your-domain.com/fullchain.pem
MI_SSL_KEY=/etc/letsencrypt/live/your-domain.com/privkey.pem
MI_PORT=443
MI_SECURE_COOKIES=true
```

### Step 3: Start the Application

```bash
# If using port 443, run with sudo
sudo -E python3 mongosync_insights.py

# Or use a non-privileged port (e.g., 8443) and set up port forwarding
export MI_PORT=8443
python3 mongosync_insights.py
```

### Step 4: Access the Application

```
https://your-domain.com
# or
https://your-domain.com:8443  (if using custom port)
```

### Step 5: Set Up Certificate Auto-Renewal

Let's Encrypt certificates expire every 90 days. Set up automatic renewal:

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Add to crontab for automatic renewal
sudo crontab -e

# Add this line (checks twice daily and renews if needed)
0 0,12 * * * certbot renew --quiet --post-hook "systemctl restart mongosync-insights"
```

Or if running manually:

```bash
# Create a renewal script
cat > /usr/local/bin/renew-mongosync-certs.sh << 'EOF'
#!/bin/bash
certbot renew --quiet
if [ $? -eq 0 ]; then
    # Restart your application here
    pkill -f mongosync_insights.py
    # Add your startup command here
fi
EOF

chmod +x /usr/local/bin/renew-mongosync-certs.sh

# Add to crontab
0 0,12 * * * /usr/local/bin/renew-mongosync-certs.sh
```

---

## Option B: Reverse Proxy (Recommended for Production)

Use a reverse proxy (Nginx or Apache) to handle SSL/TLS. This is the recommended approach for production.

### Advantages

✅ Better performance and security  
✅ Easier certificate management  
✅ Handle HTTP → HTTPS redirects  
✅ Don't need to run Flask as root  
✅ Can add load balancing, caching, etc.  
✅ Industry standard practice

### Using Nginx

#### Step 1: Install Nginx

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install nginx

# CentOS/RHEL
sudo yum install nginx

# macOS
brew install nginx
```

#### Step 2: Obtain SSL Certificates

```bash
# Install certbot with Nginx plugin
sudo apt-get install certbot python3-certbot-nginx

# Generate certificates (certbot will auto-configure Nginx)
sudo certbot --nginx -d your-domain.com
```

#### Step 3: Configure Nginx

Create or edit `/etc/nginx/sites-available/mongosync-insights`:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS server
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    
    # SSL certificates (managed by certbot)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    
    # Logging
    access_log /var/log/nginx/mongosync-insights-access.log;
    error_log /var/log/nginx/mongosync-insights-error.log;
    
    # Proxy settings
    location / {
        proxy_pass http://127.0.0.1:3030;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support (if needed in the future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Increase upload size limit (for large log files)
    client_max_body_size 10G;
}
```

#### Step 4: Enable the Site and Test Configuration

```bash
# Create symbolic link to enable the site
sudo ln -s /etc/nginx/sites-available/mongosync-insights /etc/nginx/sites-enabled/

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

#### Step 5: Configure Mongosync Insights

Keep SSL **disabled** in the application (Nginx handles SSL):

```bash
# Run on localhost only
export MI_HOST=127.0.0.1
export MI_PORT=3030
export MI_SSL_ENABLED=false

# Start the application
python3 mongosync_insights.py
```

#### Step 6: Set Up Systemd Service (Optional)

Create `/etc/systemd/system/mongosync-insights.service`:

```ini
[Unit]
Description=Mongosync Insights
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/mongosync_insights
Environment="MI_HOST=127.0.0.1"
Environment="MI_PORT=3030"
Environment="MI_SSL_ENABLED=false"
ExecStart=/usr/bin/python3 /path/to/mongosync_insights/mongosync_insights.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mongosync-insights
sudo systemctl start mongosync-insights
sudo systemctl status mongosync-insights
```

#### Step 7: Set Up Auto-Renewal

Certbot automatically sets up renewal. Verify it's working:

```bash
# Test renewal
sudo certbot renew --dry-run

# Check renewal timer
sudo systemctl status certbot.timer
```

### Using Apache

#### Step 1: Install Apache

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install apache2

# CentOS/RHEL
sudo yum install httpd mod_ssl

# Enable required modules
sudo a2enmod ssl proxy proxy_http headers rewrite
```

#### Step 2: Obtain SSL Certificates

```bash
# Install certbot with Apache plugin
sudo apt-get install certbot python3-certbot-apache

# Generate certificates
sudo certbot --apache -d your-domain.com
```

#### Step 3: Configure Apache

Create or edit `/etc/apache2/sites-available/mongosync-insights-ssl.conf`:

```apache
<VirtualHost *:80>
    ServerName your-domain.com
    
    # Redirect all HTTP to HTTPS
    RewriteEngine On
    RewriteCond %{HTTPS} off
    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName your-domain.com
    
    # SSL Configuration
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/your-domain.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/your-domain.com/privkey.pem
    
    # Security headers
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "DENY"
    
    # Proxy settings
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3030/
    ProxyPassReverse / http://127.0.0.1:3030/
    
    # Logging
    ErrorLog ${APACHE_LOG_DIR}/mongosync-insights-error.log
    CustomLog ${APACHE_LOG_DIR}/mongosync-insights-access.log combined
    
    # Increase upload size limit
    LimitRequestBody 10737418240
</VirtualHost>
```

#### Step 4: Enable and Restart Apache

```bash
# Enable the site
sudo a2ensite mongosync-insights-ssl

# Test configuration
sudo apache2ctl configtest

# Restart Apache
sudo systemctl restart apache2
```

---

## Environment Variables Reference

### SSL/TLS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_SSL_ENABLED` | `false` | Enable/disable HTTPS in Flask application |
| `MI_SSL_CERT` | `/etc/letsencrypt/live/your-domain/fullchain.pem` | Path to SSL certificate file |
| `MI_SSL_KEY` | `/etc/letsencrypt/live/your-domain/privkey.pem` | Path to SSL private key file |
| `MI_PORT` | `3030` | Port to run the application on (use 443 for HTTPS) |
| `MI_HOST` | `127.0.0.1` | Host to bind to (use 0.0.0.0 for all interfaces) |
| `MI_SECURE_COOKIES` | `true` | Enable secure cookies (requires HTTPS) |

### Example Configurations

#### Direct SSL (Production)
```bash
MI_SSL_ENABLED=true
MI_SSL_CERT=/etc/letsencrypt/live/your-domain.com/fullchain.pem
MI_SSL_KEY=/etc/letsencrypt/live/your-domain.com/privkey.pem
MI_PORT=443
MI_HOST=0.0.0.0
MI_SECURE_COOKIES=true
```

#### Behind Reverse Proxy (Production)
```bash
MI_SSL_ENABLED=false
MI_PORT=3030
MI_HOST=127.0.0.1
MI_SECURE_COOKIES=true
```

#### Local Development
```bash
MI_SSL_ENABLED=false
MI_PORT=3030
MI_HOST=127.0.0.1
MI_SECURE_COOKIES=false
```

---

## Firewall Configuration

### For Direct Flask SSL

Allow HTTPS traffic on port 443:

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 443/tcp
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# Or specify port directly
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --reload
```

### For Reverse Proxy

Allow both HTTP and HTTPS (Nginx/Apache will handle redirects):

```bash
# Ubuntu/Debian (ufw)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### Verify Firewall Status

```bash
# Ubuntu/Debian
sudo ufw status

# CentOS/RHEL
sudo firewall-cmd --list-all
```

---

## Verify HTTPS Setup

Test your HTTPS configuration after setup:

### Test SSL Certificate

```bash
# Basic connection test
curl -v https://your-domain.com

# Test with certificate validation
curl https://your-domain.com

# Check if HTTP redirects to HTTPS (for reverse proxy setups)
curl -I http://your-domain.com
```

### Check Certificate Information

```bash
# View certificate details and expiration date
openssl s_client -connect your-domain.com:443 -servername your-domain.com </dev/null 2>/dev/null | openssl x509 -noout -dates

# More detailed certificate info
openssl s_client -connect your-domain.com:443 -servername your-domain.com </dev/null 2>/dev/null | openssl x509 -noout -text
```

### Test from Browser

1. Open your browser and navigate to `https://your-domain.com`
2. Click the padlock icon in the address bar
3. Verify certificate details:
   - Valid certificate chain
   - Correct domain name
   - Valid expiration date
   - Issued by Let's Encrypt (or your CA)

### Online SSL Testing Tools

- **SSL Labs**: [https://www.ssllabs.com/ssltest/](https://www.ssllabs.com/ssltest/)
  - Comprehensive SSL/TLS testing
  - Grade your security configuration
  - Identify potential vulnerabilities

---

## Troubleshooting

### Python Command Not Found

```
ERROR: python3: command not found
```

**Solution**: Install Python 3.10 or higher:
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install python3 python3-pip

# CentOS/RHEL
sudo yum install python3 python3-pip

# macOS (using Homebrew)
brew install python@3.10

# Verify installation
python3 --version  # Should show 3.10 or higher
```

### Certificate Not Found Error

```
ERROR: SSL certificate not found: /etc/letsencrypt/live/your-domain/fullchain.pem
```

**Solution**: Verify certificate path and permissions:
```bash
sudo ls -la /etc/letsencrypt/live/your-domain/
sudo chmod 755 /etc/letsencrypt/live/
sudo chmod 755 /etc/letsencrypt/archive/
```

### Permission Denied on Port 443

```
ERROR: Permission denied: port 443
```

**Solution**: Either run with sudo or use a non-privileged port:
```bash
# Option 1: Run with sudo
sudo -E python3 mongosync_insights.py

# Option 2: Use port forwarding (Linux)
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j REDIRECT --to-port 8443
export MI_PORT=8443
python3 mongosync_insights.py

# Option 3: Use reverse proxy (recommended)
```

### Browser Shows "Not Secure"

**Possible causes:**
1. Using self-signed certificate (expected for testing)
2. Certificate expired - renew with `sudo certbot renew`
3. Certificate doesn't match domain name
4. Mixed content (HTTP resources on HTTPS page)

### Application Not Accessible After Enabling SSL

**Check:**
1. Firewall allows HTTPS traffic: `sudo ufw allow 443/tcp`
2. Certificate files exist and are readable
3. Correct domain name in certificate
4. DNS points to your server

---

## Additional Resources

- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [Certbot Documentation](https://certbot.eff.org/docs/)
- [Nginx SSL Configuration](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [Apache SSL/TLS Encryption](https://httpd.apache.org/docs/2.4/ssl/)
- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team