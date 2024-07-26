import os
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
import re
import fitz
import ebooklib
from ebooklib import epub
import io
from io import BytesIO
import base64
from datetime import datetime
import sqlite3


app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Replace with a strong, secure key

app.config['UPLOAD_FOLDER'] = 'uploads/'

# Ensure the upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

global file_data
file_data = None  # Global variable to store file data

def convert_image_to_base64(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def convert_base64_to_image(base64_str):
    return base64.b64decode(base64_str)

def extract_text_with_font_sizes(page):
    blocks = page.get_text("dict")["blocks"]
    text_with_sizes = []
    
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                for span in line["spans"]:
                    text_with_sizes.append((span["text"], span["size"]))
    
    return text_with_sizes

def extract_title(text, default="Unknown Title"):
    title_match = re.search(r'\bTitle[:\s]*(.+)', text)
    if title_match:
        return title_match.group(1).strip()
    return default

def extract_author(text, default="Unknown Author"):
    author_match = re.search(r'Copyright\s+©\s+\d{4}\s+by\s+(.+)', text)
    if author_match:
        return author_match.group(1).strip()
    return default

def extract_isbn(text, default="Unknown ISBN"):
    isbn_match = re.search(r'\bISBN(?:-10)?(?:-13)?[:\s]*([\d\-Xx]+)\b', text)
    if isbn_match:
        return isbn_match.group(1).strip()
    return default

def extract_total_pages(document):
    return len(document)

def extract_images_from_page(page, document, max_images=3):
    image_list = page.get_images(full=True)
    images = []
    
    for img_index, img in enumerate(image_list):
        if img_index >= max_images:
            break
        
        xref = img[0]
        base_image = document.extract_image(xref)
        image_bytes = base_image["image"]
        images.append(image_bytes)
    
    return images

def convert_page_to_image(page):
    pix = page.get_pixmap()
    return pix.tobytes()

def extract_cover_images(file_stream):
    images = []
    document = fitz.open(stream=file_stream, filetype="pdf")
    
    for page_num in range(min(3, len(document))):
        page = document.load_page(page_num)
        images.extend(extract_images_from_page(page, document))
    
    if len(document) > 0:
        first_page = document.load_page(0)
        first_page_image_bytes = convert_page_to_image(first_page)
        images.append(first_page_image_bytes)
    
    document.close()
    
    image_base64_list = [convert_image_to_base64(img_bytes) for img_bytes in images]
    
    return image_base64_list

def extract_pdf_details(file_stream):
    document = fitz.open(stream=file_stream, filetype="pdf")
    
    metadata = document.metadata
    book_name = metadata.get('title', 'Unknown Title')
    
    isbn = "Unknown ISBN"
    author_name = "Unknown Author"
    all_text = ""
    
    for page_num in range(min(10, len(document))):
        page = document.load_page(page_num)
        text = page.get_text()
        all_text += text + "\n\n"
        
        if book_name == "Unknown Title":
            book_name = extract_title(text, book_name)
        if author_name == "Unknown Author":
            author_name = extract_author(text, author_name)
        if isbn == "Unknown ISBN":
            isbn = extract_isbn(text, isbn)
    
    total_pages = extract_total_pages(document)
    image_base64_list = extract_cover_images(file_stream)
    
    document.close()
    
    return {
        "book_name": book_name,
        "author_name": author_name,
        "isbn_number": isbn,
        "total_pages": total_pages,
        "image_base64_list": image_base64_list,
        "original_file_stream": file_stream.getvalue(),
    }

def extract_epub_details(file_stream):
    book = epub.read_epub(file_stream)
    details = {
        'book_name': book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else 'Unknown',
        'author_name': book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else 'Unknown',
        'isbn_number': 'Unknown',
        'total_pages': 'Unknown',
    }

    for item in book.get_metadata('DC', 'identifier'):
        if 'isbn' in item[0].lower():
            details['isbn_number'] = item[0]
            break

    return details

@app.route('/upload', methods=['POST'])
def upload_file():
    global file_data

    if 'file' not in request.files:
        return 'No file part'
    
    file = request.files['file']
    
    if file.filename == '':
        return 'No selected file'
    
    if file:
        file_stream = io.BytesIO(file.read())
        file_data = file_stream.getvalue()  # Store the file data in the global variable

        if file.content_type == 'application/pdf':
            details = extract_pdf_details(file_stream)
        elif file.content_type == 'application/epub+zip':
            details = extract_epub_details(file_stream)
        else:
            return 'Unsupported file format'
        
        return jsonify({
            'book_name': details['book_name'],
            'author_name': details['author_name'],
            'isbn_number': details['isbn_number'],
            'total_pages': details['total_pages'],
            'image_base64_list': details['image_base64_list'],
            'filePath': 'path/to/file'  # You may need to handle this differently
        })

@app.route('/final_submit', methods=['POST'])
def final_submit():
    global file_data

    if not file_data:
        return 'No file data available'
    
    # Retrieve form data
    book_name = request.form.get('bookName')
    author_name = request.form.get('authorName')
    isbn_number = request.form.get('isbnNumber')
    total_pages = request.form.get('totalPages')
    category = request.form.get('category')
    subcategory = request.form.get('subcategory')
    cover_image_base64 = request.form.get('coverImage')  # Assuming this is the selected cover image base64
    keywords = request.form.get('keywords', '')
    index = request.form.get('index', '')

    # Create directories if they don't exist
    base_upload_path = 'uploads'
    category_path = os.path.join(base_upload_path, category)
    subcategory_path = os.path.join(category_path, subcategory)
    book_folder_path = os.path.join(subcategory_path, book_name)

    os.makedirs(book_folder_path, exist_ok=True)

    # Save the PDF file
    file_stream = io.BytesIO(file_data)
    pdf_path = os.path.join(book_folder_path, 'book.pdf')
    
    with open(pdf_path, 'wb') as f:
        f.write(file_data)

    # Save the cover image
    img_path = None
    if cover_image_base64:
        img_bytes = convert_base64_to_image(cover_image_base64)
        img_path = os.path.join(book_folder_path, 'cover_image.jpg')
        with open(img_path, 'wb') as f:
            f.write(img_bytes)

    # Connect to SQLite database and insert data
    conn = sqlite3.connect(r"E:\digital library\v1\digital_library.db")
    cursor = conn.cursor()

    db_insertion_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
        INSERT INTO books_table (book_name, author, isbn, total_pages, book_path, image_path, category, subcategory, keywords, book_index, db_insertion_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (book_name, author_name, isbn_number, total_pages, pdf_path, img_path, category, subcategory, keywords, index, db_insertion_time))
    
    conn.commit()
    conn.close()
    
    return 'File and images saved and data inserted successfully'

@app.route('/getadmincategories', methods=['GET'])
def get_admin_categories():
    print("hellllllllloooooo")
    conn = sqlite3.connect('E:/digital library/v1/digital_library.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    print(categories)
    conn.close()
    
    return jsonify([{'id': row[0], 'category_name': row[1]} for row in categories])

@app.route('/getadminsubcategories/<int:category_id>', methods=['GET'])
def get_admin_subcategories(category_id):
    conn = sqlite3.connect('E:/digital library/v1/digital_library.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM subcategories WHERE category_id = ?", (category_id,))
    subcategories = cursor.fetchall()
    
    conn.close()
    
    return jsonify([{'id': row[0], 'subcategory_name': row[1]} for row in subcategories])

@app.route('/add_category_and_subcategory', methods=['POST'])
def add_category_and_subcategory():
    data = request.json
    category_name = data.get('category_name')
    subcategory_name = data.get('subcategory_name')

    try:
        conn = sqlite3.connect('E:/digital library/v1/digital_library.db')
        cursor = conn.cursor()

        # Add new category
        cursor.execute("INSERT INTO categories (category_name) VALUES (?)", (category_name,))
        category_id = cursor.lastrowid

        # Add new subcategory
        cursor.execute("INSERT INTO subcategories (subcategory_name, category_id) VALUES (?, ?)", (subcategory_name, category_id))

        conn.commit()
        conn.close()
        return jsonify({"message": "Category and subcategory added successfully"}), 200

    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 400

@app.route('/add_subcategory', methods=['POST'])
def add_subcategory_to_existing_category():
    data = request.json
    category_id = data.get('category_id')
    subcategory_name = data.get('subcategory_name')
    print(category_id)
    print(subcategory_name)
    try:
        conn = sqlite3.connect('E:/digital library/v1/digital_library.db')
        cursor = conn.cursor()

        # Add new subcategory
        cursor.execute("INSERT INTO subcategories (subcategory_name, category_id) VALUES (?, ?)", (subcategory_name, category_id))

        conn.commit()
        conn.close()
        return jsonify({"message": "Subcategory added successfully"}), 200

    except sqlite3.Error as e:
        return jsonify({"error": str(e)}), 400


@app.route('/admin')
def admin_page():
    return render_template('adminindex.html')

if __name__ == "__main__":
    app.run(debug=True)
