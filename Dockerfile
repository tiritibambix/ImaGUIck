# Choisir l'image de base
FROM python:3.9-slim

# Dépendances nécessaires pour compiler ImageMagick et autres utilitaires
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    tar \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libgif-dev \
    libx11-dev \
    libxt-dev \
    libmagickcore-dev \
    libmagickwand-dev \
    exiftool \
    zip unzip \
    && rm -rf /var/lib/apt/lists/*

# Télécharger et installer ImageMagick 7.1.1-41
RUN wget https://github.com/ImageMagick/ImageMagick/archive/refs/tags/7.1.1-41.tar.gz -O /tmp/imagemagick.tar.gz \
    && tar -xvzf /tmp/imagemagick.tar.gz -C /tmp \
    && cd /tmp/ImageMagick-7.1.1-41 \
    && ./configure --prefix=/usr/local --disable-shared --without-x \
    && make -j4 \
    && make install \
    && rm -rf /tmp/*

# Ajouter /usr/local/bin au PATH
ENV PATH="/usr/local/bin:${PATH}"

# Vérifier que ImageMagick est bien installé
RUN magick -version

# Copier l'application dans le conteneur
WORKDIR /app
COPY . /app

# Installer les dépendances Python
RUN pip install --no-cache-dir -r /app/requirements.txt

# Exposer le port
EXPOSE 5000

# Commande pour démarrer l'application Flask
CMD ["python", "app.py"]
