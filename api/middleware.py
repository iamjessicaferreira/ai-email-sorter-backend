"""
Middleware to allow ngrok domains in development.
This middleware modifies ALLOWED_HOSTS before CommonMiddleware validates the host.
"""
import re
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class AllowNgrokHostMiddleware(MiddlewareMixin):
    """
    Middleware that allows ngrok domains in development mode.
    This must run BEFORE CommonMiddleware to modify ALLOWED_HOSTS before validation.
    """
    # Patterns for common ngrok domains
    ngrok_patterns = [
        r'.*\.ngrok-free\.app$',
        r'.*\.ngrok\.io$',
        r'.*\.ngrok\.app$',
    ]

    def process_request(self, request):
        """Process the request before other middleware."""
        if settings.DEBUG:
            try:
                # Get the raw host from headers (before Django validates)
                host_header = request.META.get('HTTP_HOST', '')
                if host_header:
                    host = host_header.split(':')[0]  # Remove port if present
                    
                    # Check if host matches ngrok patterns
                    is_ngrok = any(re.match(pattern, host) for pattern in self.ngrok_patterns)
                    
                    if is_ngrok:
                        # Ensure ALLOWED_HOSTS is a mutable list
                        if not isinstance(settings.ALLOWED_HOSTS, list):
                            settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) if isinstance(settings.ALLOWED_HOSTS, (list, tuple)) else [settings.ALLOWED_HOSTS]
                        
                        # Add ngrok host if not already present
                        if host not in settings.ALLOWED_HOSTS:
                            settings.ALLOWED_HOSTS.append(host)
                            print(f"[NGROK MIDDLEWARE] Added ngrok host to ALLOWED_HOSTS: {host}")
                        
                        # Also add the full host with port if present
                        if ':' in host_header and host_header not in settings.ALLOWED_HOSTS:
                            settings.ALLOWED_HOSTS.append(host_header)
            except Exception as e:
                # If anything fails, let Django handle it normally
                print(f"[NGROK MIDDLEWARE] Error: {e}")
                import traceback
                traceback.print_exc()
        
        return None  # Continue processing
