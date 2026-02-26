__version__ = "0.1.0"

# Force aiohttp to use ThreadedResolver (stdlib socket.getaddrinfo) instead of
# aiodns (C-ARES), which fails on certain Windows DNS configurations.
# Must patch both resolver module AND connector module (which caches the import).
import aiohttp.resolver  # noqa: E402
import aiohttp.connector  # noqa: E402

aiohttp.resolver.DefaultResolver = aiohttp.resolver.ThreadedResolver
aiohttp.connector.DefaultResolver = aiohttp.resolver.ThreadedResolver
