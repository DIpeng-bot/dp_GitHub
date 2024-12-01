from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime
import fitz  # PyMuPDF
from PIL import Image
import io
import ebooklib
from ebooklib import epub
import base64
import re
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# 配置上传文件夹
UPLOAD_FOLDER = 'static/uploads'
COVERS_FOLDER = 'static/covers'
ALLOWED_EXTENSIONS = {'pdf', 'epub'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COVERS_FOLDER'] = COVERS_FOLDER

# 确保上传目录存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(COVERS_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS magazines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            category TEXT NOT NULL,
            format TEXT NOT NULL,
            upload_date DATETIME NOT NULL,
            cover_image TEXT
        )
    ''')
    conn.commit()
    conn.close()

def extract_cover_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        
        # 遍历前5页，找到第一个非空白页面
        for page_num in range(min(5, len(doc))):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            
            # 检查页面是否为空白
            img_data = pix.tobytes()
            img = Image.frombytes("RGB", [pix.width, pix.height], img_data)
            
            # 转换为灰度图并计算平均像素值
            gray_img = img.convert('L')
            avg_pixel = sum(gray_img.getdata()) / (gray_img.width * gray_img.height)
            
            # 如果页面不是纯白（平均像素值小于250），则使用该页面
            if avg_pixel < 250:
                print(f"使用第 {page_num + 1} 页作为封面，平均像素值: {avg_pixel}")
                
                # 调整图片大小
                img.thumbnail((300, 400), Image.Resampling.LANCZOS)
                
                # 保存为JPEG
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr = img_byte_arr.getvalue()
                
                doc.close()
                return img_byte_arr
            else:
                print(f"跳过第 {page_num + 1} 页，因为它可能是空白页（平均像素值: {avg_pixel}）")
        
        # 如果前5页都是空白的，使用第一页
        print("未找到合适的封面，使用第一页")
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_data = pix.tobytes()
        img = Image.frombytes("RGB", [pix.width, pix.height], img_data)
        
        # 调整图片大小
        img.thumbnail((300, 400), Image.Resampling.LANCZOS)
        
        # 保存为JPEG
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        img_byte_arr = img_byte_arr.getvalue()
        
        doc.close()
        return img_byte_arr
        
    except Exception as e:
        print(f"PDF封面提取错误: {e}")
        return None

def extract_cover_from_epub(epub_path):
    try:
        book = epub.read_epub(epub_path)
        
        # 尝试从元数据中获取封面
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_COVER or \
               item.get_type() == ebooklib.ITEM_IMAGE:
                img_data = item.get_content()
                img = Image.open(io.BytesIO(img_data))
                
                # 调整图片大小
                img.thumbnail((300, 400), Image.Resampling.LANCZOS)
                
                # 保存为JPEG
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG', quality=85)
                img_byte_arr = img_byte_arr.getvalue()
                
                return img_byte_arr
        
        return None
    except Exception as e:
        print(f"EPUB封面提取错误: {e}")
        return None

def save_cover_image(cover_data, filename):
    if cover_data:
        cover_path = os.path.join(app.config['COVERS_FOLDER'], f"cover_{filename}.jpg")
        with open(cover_path, 'wb') as f:
            f.write(cover_data)
        return f"cover_{filename}.jpg"
    return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    c.execute('SELECT * FROM magazines ORDER BY upload_date DESC')
    magazines = c.fetchall()
    c.execute('SELECT DISTINCT category FROM magazines')
    categories = [row[0] for row in c.fetchall()]
    conn.close()
    return render_template('index.html', 
                         magazines=magazines, 
                         categories=categories,
                         current_category='all',
                         current_format='all')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('没有选择文件')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('没有选择文件')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_format = filename.rsplit('.', 1)[1].lower()
        title = request.form.get('title', filename)
        category = request.form.get('category', '未分类')
        
        # 保存文件
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # 提取并保存封面
        if file_format == 'pdf':
            cover_data = extract_cover_from_pdf(file_path)
        else:  # epub
            cover_data = extract_cover_from_epub(file_path)
        
        cover_filename = save_cover_image(cover_data, filename)
        
        # 保存到数据库
        conn = sqlite3.connect('magazines.db')
        c = conn.cursor()
        c.execute('''
            INSERT INTO magazines (title, filename, category, format, upload_date, cover_image)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (title, filename, category, file_format, datetime.now(), cover_filename))
        conn.commit()
        conn.close()
        
        flash('文件上传成功！')
        return redirect(url_for('index'))
    
    flash('不支持的文件格式')
    return redirect(url_for('index'))

@app.route('/delete/<int:id>')
def delete_magazine(id):
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    # 获取文件名和封面图片名
    c.execute('SELECT filename, cover_image FROM magazines WHERE id = ?', (id,))
    result = c.fetchone()
    
    if result:
        filename, cover_image = result
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        cover_path = os.path.join(app.config['COVERS_FOLDER'], cover_image) if cover_image else None
        
        # 从数据库中删除记录
        c.execute('DELETE FROM magazines WHERE id = ?', (id,))
        conn.commit()
        
        # 删除文件
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # 删除封面图片
        if cover_path and os.path.exists(cover_path):
            os.remove(cover_path)
            
        flash('杂志已成功删除！')
    else:
        flash('未找到该杂志！')
    
    conn.close()
    return redirect(url_for('index'))

@app.route('/download/<int:id>')
def download_magazine(id):
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    c.execute('SELECT filename, title FROM magazines WHERE id = ?', (id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        filename = result[0]
        title = result[1]
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            filename,
            as_attachment=True,
            download_name=f"{title}.{filename.split('.')[-1]}"
        )
    
    flash('未找到该杂志！')
    return redirect(url_for('index'))

@app.route('/filter')
def filter_magazines():
    category = request.args.get('category', 'all')
    file_format = request.args.get('format', 'all')
    
    conn = sqlite3.connect('magazines.db')
    c = conn.cursor()
    
    query = 'SELECT * FROM magazines WHERE 1=1'
    params = []
    
    if category and category != 'all':
        query += ' AND category = ?'
        params.append(category)
    
    if file_format and file_format != 'all':
        query += ' AND format = ?'
        params.append(file_format)
    
    query += ' ORDER BY upload_date DESC'
    
    c.execute(query, params)
    magazines = c.fetchall()
    c.execute('SELECT DISTINCT category FROM magazines')
    categories = [row[0] for row in c.fetchall()]
    conn.close()
    
    return render_template('index.html', 
                         magazines=magazines, 
                         categories=categories,
                         current_category=category,
                         current_format=file_format)

if __name__ == '__main__':
    init_db()
    app.run(debug=True) 