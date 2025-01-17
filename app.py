from flask import Flask, render_template, request, redirect, url_for, send_file, flash, Response
import os
import subprocess
from zipfile import ZipFile
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image
import requests
import logging
import re

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
DEFAULTS = {
    "quality": "100",
    "width": "",
    "height": "",
    "percentage": "",
}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.secret_key = 'supersecretkey'
app.logger.setLevel(logging.INFO)

def allowed_file(filename):
    """Allow all file types supported by ImageMagick."""
    return '.' in filename

def get_image_dimensions(filepath):
    """Get image dimensions using appropriate tool based on file type."""
    try:
        if filepath.lower().endswith('.arw'):
            app.logger.info(f"Getting dimensions for ARW file: {filepath}")
            # Utiliser exiftool pour obtenir les dimensions de l'aperçu JPEG
            cmd = ['exiftool', '-s', '-s', '-s', '-PreviewImageLength', '-PreviewImageWidth', filepath]
            app.logger.info(f"Running exiftool command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                app.logger.info(f"Exiftool output: {result.stdout}")
                # Essayer de parser les dimensions
                dimensions = result.stdout.strip().split('\n')
                if len(dimensions) == 2:
                    try:
                        height = int(dimensions[0])
                        width = int(dimensions[1])
                        app.logger.info(f"Successfully parsed dimensions: {width}x{height}")
                        return width, height
                    except ValueError:
                        app.logger.warning("Could not parse dimensions from exiftool output")
                        pass
            else:
                app.logger.warning(f"Exiftool failed or no output: {result.stderr}")
            
            # Si on n'a pas pu obtenir les dimensions de l'aperçu, utiliser les dimensions connues
            app.logger.info("Using known dimensions for Sony A7 IV")
            return 7008, 4672  # Dimensions connues pour Sony A7 IV
        else:
            app.logger.info(f"Getting dimensions for non-ARW file: {filepath}")
            cmd = ['convert', 'identify', filepath]
            app.logger.info(f"Running ImageMagick command: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Error getting image dimensions: {result.stderr}")
            
            app.logger.info(f"ImageMagick output: {result.stdout}")
            # Parse the output to get dimensions
            match = re.search(r'\s(\d+)x(\d+)\s', result.stdout)
            if match:
                width = int(match.group(1))
                height = int(match.group(2))
                app.logger.info(f"Successfully parsed dimensions: {width}x{height}")
                return width, height
            else:
                raise Exception("Could not parse image dimensions")
    except Exception as e:
        app.logger.error(f"Error getting image dimensions: {str(e)}")
        return None, None

def get_available_formats():
    """Get all formats supported by ImageMagick."""
    try:
        # Exécute la commande magick -list format pour obtenir tous les formats supportés
        result = subprocess.run(['magick', '-list', 'format'], capture_output=True, text=True)
        formats = []
        
        # Parse la sortie pour extraire les formats
        for line in result.stdout.split('\n'):
            # Ignore l'en-tête et les lignes vides
            if line.strip() and not line.startswith('Format') and not line.startswith('--'):
                # Le format est le premier mot de chaque ligne
                format_name = line.split()[0].upper()
                # Certains formats ont des suffixes comme * ou +, on les enlève
                format_name = format_name.rstrip('*+')
                if format_name not in formats:
                    formats.append(format_name)
        
        return formats
    except Exception as e:
        app.logger.error(f"Erreur lors de la récupération des formats : {e}")
        # Liste de secours avec les formats les plus courants
        return ['PNG', 'JPEG', 'GIF', 'TIFF', 'BMP', 'WEBP']

def get_format_categories():
    """Categorize image formats by their typical usage."""
    return {
        'transparency': {
            'recommended': ['PNG', 'WEBP', 'AVIF', 'HEIC', 'GIF'],
            'compatible': ['TIFF', 'ICO', 'JXL', 'PSD', 'SVG', 'TGA']
        },
        'photo': {
            'recommended': ['JPEG', 'WEBP', 'AVIF', 'HEIC', 'JXL', 'TIFF'],
            'compatible': [
                # Formats RAW
                'ARW', 'CR2', 'CR3', 'NEF', 'NRW', 'ORF', 'RAF', 'RW2', 'PEF', 'DNG',
                'IIQ', 'KDC', '3FR', 'MEF', 'MRW', 'SRF', 'X3F',
                # Autres formats photo
                'PNG', 'BMP', 'PPM', 'JP2', 'HDR', 'EXR', 'DPX', 'MIFF', 'MNG',
                'PCD', 'RGBE', 'YCbCr', 'CALS'
            ]
        },
        'graphic': {
            'recommended': ['PNG', 'WEBP', 'GIF', 'SVG'],
            'compatible': [
                'JPEG', 'TIFF', 'BMP', 'PCX', 'TGA', 'ICO', 'WBMP', 'XPM',
                'DIB', 'EMF', 'WMF', 'PICT', 'MacPICT', 'EPT', 'EPDF', 'EPI', 'EPS',
                'EPSF', 'EPSI', 'EPT', 'PDF', 'PS', 'AI', 'MONO'
            ]
        }
    }

def get_recommended_formats(image_type):
    """Get recommended and compatible formats based on image type."""
    categories = get_format_categories()
    available_formats = set(get_available_formats())
    
    if image_type['has_transparency']:
        category = 'transparency'
    elif image_type['is_photo']:
        category = 'photo'
    else:
        category = 'graphic'
        
    # Récupère les formats recommandés et compatibles pour cette catégorie
    recommended = [fmt for fmt in categories[category]['recommended'] 
                  if fmt in available_formats]
    compatible = [fmt for fmt in categories[category]['compatible'] 
                 if fmt in available_formats]
    
    # Ajoute le format original s'il n'est pas déjà présent
    original_format = image_type.get('original_format')
    if original_format:
        original_format = original_format.upper()
        if original_format not in recommended and original_format not in compatible:
            if original_format in available_formats:
                compatible.append(original_format)
    
    return {
        'recommended': recommended,
        'compatible': compatible
    }

def analyze_image_type(filepath):
    """Analyze image to determine its type and best suitable formats."""
    try:
        # Vérifier si c'est un fichier RAW
        if filepath.lower().endswith('.arw'):
            app.logger.info(f"Analyzing RAW file: {filepath}")
            return {
                'has_transparency': False,
                'is_photo': True,
                'original_format': 'ARW'
            }
            
        # Pour les autres formats, utiliser PIL
        with Image.open(filepath) as img:
            has_transparency = 'A' in img.getbands()
            is_photo = True
            
            # Check if image is more like a photo or graphic
            if img.mode in ('P', '1', 'L'):
                is_photo = False
            elif img.mode in ('RGB', 'RGBA'):
                # Sample pixels to determine if it's likely a photo
                pixels = list(img.getdata())
                unique_colors = len(set(pixels[:1000]))  # Sample first 1000 pixels
                is_photo = unique_colors > 100  # If many unique colors, likely a photo
            
            return {
                'has_transparency': has_transparency,
                'is_photo': is_photo,
                'original_format': img.format
            }
    except Exception as e:
        app.logger.error(f"Error analyzing image: {e}")
        # En cas d'erreur, supposer que c'est une photo sans transparence
        return {
            'has_transparency': False,
            'is_photo': True,
            'original_format': None
        }

def flash_error(message):
    """Flash error message and log if needed."""
    flash(message)
    app.logger.error(message)

def build_imagemagick_command(filepath, output_path, width, height, percentage, quality, keep_ratio):
    """Build ImageMagick command for resizing and formatting."""
    # Pour les fichiers RAW Sony ARW, on extrait le JPEG intégré
    if filepath.lower().endswith('.arw'):
        app.logger.info(f"Processing ARW file: {filepath}")
        # Créer un nom temporaire pour le fichier JPEG extrait
        temp_jpeg = os.path.join(os.path.dirname(output_path), f"{os.path.splitext(os.path.basename(filepath))[0]}_preview.jpg")
        app.logger.info(f"Temporary JPEG will be saved as: {temp_jpeg}")
        
        # Essayer d'abord JpgFromRaw (meilleure qualité)
        app.logger.info("Attempting to extract JpgFromRaw...")
        exif_cmd = ['exiftool', '-b', '-JpgFromRaw', filepath]
        app.logger.info(f"Running exiftool command: {' '.join(exif_cmd)}")
        result = subprocess.run(exif_cmd, capture_output=True)
        
        if result.returncode == 0 and result.stdout.strip():
            app.logger.info("Successfully extracted JpgFromRaw")
            # Sauvegarder le JPEG extrait
            with open(temp_jpeg, 'wb') as f:
                f.write(result.stdout)
            app.logger.info(f"Saved JpgFromRaw to: {temp_jpeg}")
        else:
            app.logger.info("No JpgFromRaw found, trying PreviewImage...")
            # Si pas de JpgFromRaw, essayer PreviewImage
            exif_cmd = ['exiftool', '-b', '-PreviewImage', filepath]
            app.logger.info(f"Running exiftool command: {' '.join(exif_cmd)}")
            result = subprocess.run(exif_cmd, capture_output=True)
            if result.returncode == 0 and result.stdout.strip():
                app.logger.info("Successfully extracted PreviewImage")
                with open(temp_jpeg, 'wb') as f:
                    f.write(result.stdout)
                app.logger.info(f"Saved PreviewImage to: {temp_jpeg}")
            else:
                app.logger.error(f"Exiftool error: {result.stderr.decode('utf-8', errors='ignore')}")
                raise Exception("No preview image found in RAW file")
        
        # Commande ImageMagick pour redimensionner le JPEG extrait
        magick_cmd = ['convert', temp_jpeg]
        
        if width.isdigit() and height.isdigit():
            resize_value = f"{width}x{height}" if keep_ratio else f"{width}x{height}!"
            magick_cmd.extend(["-resize", resize_value])
            app.logger.info(f"Adding resize parameters: {resize_value}")
        elif percentage.isdigit() and 0 < int(percentage) <= 100:
            magick_cmd.extend(["-resize", f"{percentage}%"])
            app.logger.info(f"Adding percentage resize: {percentage}%")
            
        if quality.isdigit() and 1 <= int(quality) <= 100:
            magick_cmd.extend(["-quality", quality])
            app.logger.info(f"Setting quality to: {quality}")
            
        magick_cmd.append(output_path)
        app.logger.info(f"Final ImageMagick command: {' '.join(magick_cmd)}")
        return None, magick_cmd, temp_jpeg
    else:
        app.logger.info(f"Processing non-ARW file: {filepath}")
        # Pour les autres formats, utiliser directement ImageMagick
        command = ['convert', filepath]
        
        if width.isdigit() and height.isdigit():
            resize_value = f"{width}x{height}" if keep_ratio else f"{width}x{height}!"
            command.extend(["-resize", resize_value])
            app.logger.info(f"Adding resize parameters: {resize_value}")
        elif percentage.isdigit() and 0 < int(percentage) <= 100:
            command.extend(["-resize", f"{percentage}%"])
            app.logger.info(f"Adding percentage resize: {percentage}%")
            
        if quality.isdigit() and 1 <= int(quality) <= 100:
            command.extend(["-quality", quality])
            app.logger.info(f"Setting quality to: {quality}")
            
        command.append(output_path)
        app.logger.info(f"Final ImageMagick command: {' '.join(command)}")
        return None, command, None

@app.route('/')
def index():
    """Homepage with upload options."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file uploads."""
    if 'file' not in request.files:
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('index'))
        
    files = request.files.getlist('file')
    if not files or all(file.filename == '' for file in files):
        flash('Veuillez sélectionner au moins un fichier', 'error')
        return redirect(url_for('index'))
        
    uploaded_files = []
    for file in files:
        if file and allowed_file(file.filename):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
            file.save(filepath)
            uploaded_files.append(filepath)
        else:
            flash_error(f"Unsupported file format for {file.filename}.")

    if len(uploaded_files) == 1:
        return redirect(url_for('resize_options', filename=os.path.basename(uploaded_files[0])))
    if len(uploaded_files) > 1:
        return redirect(url_for('resize_batch_options', filenames=','.join(map(os.path.basename, uploaded_files))))
    return redirect(url_for('index'))

@app.route('/upload_url', methods=['POST'])
def upload_url():
    """Handle image upload from a URL."""
    url = request.form.get('url')
    if not url:
        return flash_error("No URL provided."), redirect(url_for('index'))

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, stream=True, headers=headers)
        response.raise_for_status()

        filename = url.split("/")[-1].split("?")[0]
        if not filename:
            return flash_error("Unable to determine a valid filename from the URL."), redirect(url_for('index'))

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        flash(f"Image downloaded successfully: {filename}")
        return redirect(url_for('resize_options', filename=filename))
    except requests.exceptions.RequestException as e:
        return flash_error(f"Error downloading image: {e}"), redirect(url_for('index'))

@app.route('/resize_options/<filename>')
def resize_options(filename):
    """Resize options page for a single image."""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    dimensions = get_image_dimensions(filepath)
    if not dimensions:
        return redirect(url_for('index'))

    # Analyze image and get recommended formats
    image_type = analyze_image_type(filepath)
    if image_type:
        format_info = get_recommended_formats(image_type)
        formats = {
            'recommended': format_info['recommended'],
            'compatible': format_info['compatible']
        }
    else:
        formats = {
            'recommended': [],
            'compatible': get_available_formats()
        }

    width, height = dimensions
    return render_template('resize.html', 
                         filename=filename, 
                         width=width, 
                         height=height, 
                         formats=formats, 
                         image_type=image_type)

@app.route('/resize/<filename>', methods=['POST'])
def resize_image(filename):
    """Handle resizing or format conversion for a single image."""
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    name, ext = os.path.splitext(filename)
    output_filename = f"{name}_rsz{ext}"
    format_conversion = request.form.get('format', None)
    if format_conversion:
        output_filename = f"{name}_rsz.{format_conversion.lower()}"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

    command = build_imagemagick_command(
        filepath=filepath,
        output_path=output_path,
        width=request.form.get('width', DEFAULTS["width"]),
        height=request.form.get('height', DEFAULTS["height"]),
        percentage=request.form.get('percentage', DEFAULTS["percentage"]),
        quality=request.form.get('quality', DEFAULTS["quality"]),
        keep_ratio='keep_ratio' in request.form
    )

    try:
        subprocess.run(command[1], check=True)
        flash(f'Image processed successfully: {output_filename}')
        return redirect(url_for('download', filename=output_filename))
    except Exception as e:
        return flash_error(f"Error processing image: {e}"), redirect(url_for('resize_options', filename=filename))

@app.route('/resize_batch_options/<filenames>')
def resize_batch_options(filenames):
    """Resize options page for batch processing."""
    files = filenames.split(',')
    
    # Analyze each image and get common recommended formats
    image_types = []
    has_transparency = False
    has_photos = False
    has_graphics = False
    
    for filename in files:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_type = analyze_image_type(filepath)
        if image_type:
            image_types.append({'filename': filename, 'type': image_type})
            has_transparency = has_transparency or image_type['has_transparency']
            has_photos = has_photos or image_type['is_photo']
            has_graphics = has_graphics or not image_type['is_photo']
    
    # Create a combined image type for the batch
    batch_type = {
        'has_transparency': has_transparency,
        'is_photo': has_photos,
        'original_format': None  # Not relevant for batch
    }
    
    # Get format recommendations for the batch
    format_info = get_recommended_formats(batch_type)
    
    batch_info = {
        'has_transparency': has_transparency,
        'has_photos': has_photos,
        'has_graphics': has_graphics
    }
    
    return render_template('resize_batch.html', 
                         files=files, 
                         formats=format_info, 
                         image_types=image_types,
                         batch_info=batch_info)

@app.route('/resize_batch', methods=['POST'])
def resize_batch():
    """Resize multiple images and compress them into a ZIP."""
    filenames = request.form.get('filenames').split(',')
    output_files = []

    for filename in filenames:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        name, ext = os.path.splitext(filename)
        output_filename = f"{name}_rsz{ext}"
        format_conversion = request.form.get('format', None)
        if format_conversion:
            output_filename = f"{name}_rsz.{format_conversion.lower()}"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

        command = build_imagemagick_command(
            filepath=filepath,
            output_path=output_path,
            width=request.form.get('width', DEFAULTS["width"]),
            height=request.form.get('height', DEFAULTS["height"]),
            percentage=request.form.get('percentage', DEFAULTS["percentage"]),
            quality=request.form.get('quality', DEFAULTS["quality"]),
            keep_ratio='keep_ratio' in request.form
        )

        try:
            subprocess.run(command[1], check=True)
            output_files.append(output_path)
        except Exception as e:
            flash_error(f"Error processing {filename}: {e}")

    if len(output_files) > 1:
        zip_suffix = datetime.now().strftime("%y%m%d-%H%M")
        zip_filename = f"batch_output_{zip_suffix}.zip"
        zip_path = os.path.join(app.config['OUTPUT_FOLDER'], zip_filename)
        with ZipFile(zip_path, 'w') as zipf:
            for file in output_files:
                zipf.write(file, os.path.basename(file))
        return redirect(url_for('download_batch', filename=zip_filename))
    elif len(output_files) == 1:
        return redirect(url_for('download', filename=os.path.basename(output_files[0])))
    else:
        return flash_error("No images processed."), redirect(url_for('index'))

@app.route('/download_batch/<filename>')
def download_batch(filename):
    """Serve the ZIP file for download."""
    zip_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    return send_file(zip_path, as_attachment=True)

@app.route('/download/<filename>')
def download(filename):
    """Serve a single file for download."""
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    with open(filepath, 'rb') as f:
        response = Response(f.read(), mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)