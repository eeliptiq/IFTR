from pydantic import BaseModel
import ssl
import certifi

class MobilePrivacySettings(BaseModel):
    """Settings optimized for GrapheneOS/CalyxOS"""
    use_tor_for_requests: bool = False
    vpn_aware: bool = True  # Don't break if VPN drops
    background_location: bool = False  # Critical for privacy
    clipboard_protection: bool = True  # Don't read clipboard
    screenshot_protection: bool = False  # Optional for sensitive data

    # GrapheneOS-specific features
    sandboxed_google_play: bool = False  # If using GMS in sandbox
    network_permission_scope: str = "internet"  # vs "network"


# Support for Tor, VPNs, and privacy networks
class NetworkPrivacyLayer:
    """Respect user's network privacy choices"""

    def __init__(self):
        self.supports_tor = True
        self.vpn_aware = True
        self.dns_over_https = True

    def make_request(self, endpoint: str, data: dict):
        """Make request respecting privacy settings"""
        # Use system proxy settings
        # Respect "Block connections without VPN"
        # Implement onion routing if enabled


class PrivacyPushNotifications:
    """Notification system that doesn't rely on GMS/FCM"""

    def __init__(self):
        self.use_websockets = True
        self.use_unified_push = True  # https://unifiedpush.org
        self.fallback_email = True

    def send_notification(self, user_id: str, message: str):
        """Try multiple channels based on user preferences"""
        # 1. WebSocket (if app foreground)
        # 2. UnifiedPush (privacy-focused alternative)
        # 3. Email fallback
        # 4. In-app message queue


class SecureMobileClient:
    """Enhanced security for mobile deployments"""

    def __init__(self):
        # Use system certs + additional pinning
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

        # Certificate pinning for your API domain
        self.ssl_context.load_verify_locations('api_iftr_pinned_certs.pem')

        # Enable TLS 1.3 only (GrapheneOS standard)
        self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3
        self.ssl_context.maximum_version = ssl.TLSVersion.TLSv1_3

    def make_secure_request(self, url: str):
        """Make request with enhanced mobile security"""
        # Implement Certificate Transparency logging checks
        # Implement OCSP stapling verification
        # Add mobile-specific headers
        pass