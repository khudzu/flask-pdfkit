from flask import Flask, render_template, \
  request, redirect, url_for
from html.parser import HTMLParser
import hashlib
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(BASE_DIR, 'vendor')
if VENDOR_DIR not in sys.path:
   sys.path.insert(0, VENDOR_DIR)

import pdfkit
import qrcode
from qrcode.constants import ERROR_CORRECT_M

def find_wkhtmltopdf():
   candidates = [
      os.environ.get('WKHTMLTOPDF_PATH'),
      os.path.join(BASE_DIR, 'wkhtmltox', 'bin', 'wkhtmltopdf.exe'),
      os.path.join(os.path.dirname(BASE_DIR), 'digitalsignature', 'wkhtmltox', 'bin', 'wkhtmltopdf.exe'),
      r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
      r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
      '/usr/bin/wkhtmltopdf',
      '/usr/local/bin/wkhtmltopdf',
   ]
   for candidate in candidates:
      if candidate and os.path.exists(candidate):
         return candidate
   return candidates[0] or candidates[1]


application = Flask(__name__)
application.config['DB_NAME'] = os.path.join(BASE_DIR, 'database.db')
application.config['PDF_FOLDER'] = os.path.join(BASE_DIR, 'static', 'pdf')
application.config['GENERATED_FOLDER'] = os.path.join(BASE_DIR, 'generated')
application.config['WKHTMLTOPDF_PATH'] = find_wkhtmltopdf()

conn = cursor = None


class TextExtractor(HTMLParser):
   def __init__(self):
      super().__init__()
      self.parts = []
      self.skip_depth = 0

   def handle_starttag(self, tag, attrs):
      if tag in ('script', 'style'):
         self.skip_depth += 1

   def handle_endtag(self, tag):
      if tag in ('script', 'style') and self.skip_depth:
         self.skip_depth -= 1

   def handle_data(self, data):
      if self.skip_depth:
         return
      text = data.strip()
      if text:
         self.parts.append(text)


def extract_text(html):
   parser = TextExtractor()
   parser.feed(html)
   return ' '.join(parser.parts)


def make_qr_html(payload):
   qr = qrcode.QRCode(
      error_correction=ERROR_CORRECT_M,
      box_size=8,
      border=2,
   )
   qr.add_data(payload)
   qr.make(fit=True)
   matrix = qr.get_matrix()
   rows = []
   for row in matrix:
      cells = []
      for filled in row:
         color = '#000' if filled else '#fff'
         cells.append(f'<td style="width: 4px; height: 4px; background: {color}; padding: 0; line-height: 0;"></td>')
      rows.append('<tr>' + ''.join(cells) + '</tr>')
   return '<table cellspacing="0" cellpadding="0" style="border-collapse: collapse; border: 8px solid #fff; background: #fff;">' + ''.join(rows) + '</table>'


def add_digital_signature(html):
   document_text = extract_text(html)
   digest = hashlib.sha256(document_text.encode('utf-8')).hexdigest()
   qr_payload = f'SHA-256:{digest}'
   qr_html = make_qr_html(qr_payload)
   signature_html = f'''
   <hr style="margin-top: 32px;" />
   <section style="margin-top: 16px; font-family: Arial, sans-serif; font-size: 12px;">
      <h3 style="margin: 0 0 8px 0;">Tanda Tangan Digital</h3>
      <p style="margin: 0 0 8px 0;">Message Digest (SHA-256):</p>
      <p style="margin: 0 0 12px 0; word-break: break-all; font-family: Consolas, monospace;">{digest}</p>
      <div style="width: 180px;">{qr_html}</div>
   </section>
   '''

   return html.replace('</body>', signature_html + '\n</body>') if '</body>' in html else html + signature_html


def openDb():
   global conn, cursor
   conn = sqlite3.connect(application.config['DB_NAME'])
   cursor = conn.cursor()


def closeDb():
   global conn, cursor
   cursor.close()
   conn.close()


def get_all_buku():
   openDb()
   container = []
   for id, judul, penulis, penerbit in cursor.execute('SELECT * FROM buku ORDER BY id'):
      container.append((id, judul, penulis, penerbit))
   closeDb()
   return container


@application.route('/')
def index():
   return render_template('index.html', container=get_all_buku())


@application.route('/tambah', methods=['GET','POST'])
def tambah():
   if request.method == 'POST':
      id = request.form['id']
      judul = request.form['judul']
      penulis = request.form['penulis']
      penerbit = request.form['penerbit']
      data = id, judul, penulis, penerbit
      openDb()
      cursor.execute('INSERT INTO buku VALUES(?,?,?,?)', data)
      conn.commit()
      closeDb()
      return redirect(url_for('index'))
   else:
      return render_template('tambah_form.html')


@application.route('/ubah/<id>', methods=['GET','POST'])
def ubah(id):
   openDb()
   cursor.execute('SELECT * FROM buku WHERE id=?', (id,))
   data = cursor.fetchone()
   if request.method == 'POST':
      id = request.form['id']
      judul = request.form['judul']
      penulis = request.form['penulis']
      penerbit = request.form['penerbit']
      cursor.execute('''
         UPDATE buku SET judul=?, penulis=?, penerbit=?
         WHERE id=?
      ''', (judul, penulis, penerbit, id))
      conn.commit()
      closeDb()
      return redirect(url_for('index'))
   else:
      closeDb()
      return render_template('ubah_form.html', data=data)


@application.route('/hapus/<id>', methods=['GET','POST'])
def hapus(id):
   openDb()
   cursor.execute('DELETE FROM buku WHERE id=?', (id,))
   conn.commit()
   closeDb()
   return redirect(url_for('index'))


@application.route('/pdf')
def pdf():
   os.makedirs(application.config['PDF_FOLDER'], exist_ok=True)
   os.makedirs(application.config['GENERATED_FOLDER'], exist_ok=True)

   wkhtmltopdf_path = application.config['WKHTMLTOPDF_PATH']
   if not os.path.exists(wkhtmltopdf_path):
      return f'''
        wkhtmltopdf belum ditemukan di: {wkhtmltopdf_path}<br />
        Set environment variable WKHTMLTOPDF_PATH ke lokasi wkhtmltopdf.exe.
      ''', 500

   html = render_template('laporan_pdf.html', container=get_all_buku())
   signed_html = add_digital_signature(html)
   signed_htmlfile = os.path.join(application.config['GENERATED_FOLDER'], 'laporan-buku-signed.html')
   pdffile = os.path.join(application.config['PDF_FOLDER'], 'laporan-buku.pdf')

   with open(signed_htmlfile, 'w', encoding='utf-8') as file:
      file.write(signed_html)

   config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
   pdfkit.from_file(signed_htmlfile, pdffile, configuration=config)
   return f'''
     PDF laporan buku berhasil dibuat.<br />Klik
     <a href="{url_for('static', filename='pdf/laporan-buku.pdf')}">di sini</a>
     untuk membuka file tersebut.
   '''


if __name__ == '__main__':
   application.run(debug=True)