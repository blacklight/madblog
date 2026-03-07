FROM quay.io/blacklight/madblog

USER root

RUN apk add --no-cache \
    chromium \
    fontconfig \
    npm \
    nss \
    texlive \
    texlive-dvi \
    ttf-dejavu \
    && rm -rf /var/cache/apk/*

# Support for Mermaid diagrams
RUN npm install -g @mermaid-js/mermaid-cli

# Support for ActivityPub
RUN pip install --no-cache-dir --prefix=/usr/local pubby

# Tell puppeteer/mermaid where chromium is and to not download its own
ENV PUPPETEER_SKIP_DOWNLOAD=1
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser

# --- chromium wrapper to force no-sandbox in restricted containers ---
COPY docker/chromium-browser-wrapper.sh /usr/local/bin
RUN set -eux; \
    mv /usr/bin/chromium-browser /usr/bin/chromium-browser.real; \
    mv /usr/local/bin/chromium-browser-wrapper.sh /usr/bin/chromium-browser

USER madblog
