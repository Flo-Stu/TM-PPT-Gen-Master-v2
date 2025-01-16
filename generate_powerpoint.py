import os
import io
import time
import threading
import uuid
import json
import requests
from flask import Flask, request, jsonify, send_file, url_for
from flask_cors import CORS
from pptx import Presentation
from pptx.util import Inches
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.chart.data import CategoryChartData

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

POTX_URL = "https://files.assistantos.de/powerpoint/DB_PPT-Template_16-9-data.potx"
generated_files = {}  # Speichert Dateien und deren Erstellungszeit
TTL = 7 * 24 * 60 * 60  # Lebensdauer der Datei in Sekunden (7 Tage)

def cleanup_files():
    """Entfernt abgelaufene Dateien."""
    while True:
        time.sleep(60)  # Überprüfung alle 60 Sekunden
        now = time.time()
        expired_files = [file_id for file_id, (file_path, timestamp) in generated_files.items() if now - timestamp > TTL]
        for file_id in expired_files:
            try:
                os.remove(file_path)  # Löscht die Datei
                del generated_files[file_id]  # Entfernt Eintrag aus dem Dictionary
            except Exception as e:
                print(f"Fehler beim Löschen der Datei {file_id}: {e}")

threading.Thread(target=cleanup_files, daemon=True).start()

def escape_text(text: str) -> str:
    """Bereinigt den Text von HTML und Markdown."""
    if not text:
        return ""
    return text.replace("\n", "\n")

@app.route('/generate_pptx', methods=['POST', 'OPTIONS'])
def generate_pptx():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'OK'}), 200

    try:
        request_body = request.get_data(as_text=True)
        data = json.loads(request_body)
        slides_data = data.get('slides', {})

        # Lade das PowerPoint-Template
        potx_response = requests.get(POTX_URL)
        potx_response.raise_for_status()
        prs = Presentation(io.BytesIO(potx_response.content))

        # Title Slide
        if 'title_slide' in slides_data:
            title_slide_data = slides_data['title_slide']
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = escape_text(title_slide_data.get('title', ''))
            slide.placeholders[1].text = escape_text(title_slide_data.get('subtitle', ''))

        # Content Slides
        for slide_data in slides_data.get('content_slides', []):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            
            # Haupttext in Platzhalter einfügen
            if 'body' in slide_data:
                placeholder_idx = slide_data.get('placeholder_idx_body', 1)
                placeholder = slide.placeholders[placeholder_idx]
                placeholder.text = escape_text(slide_data['body'])

            # Bilder in Platzhalter einfügen
            if 'images' in slide_data:
                for img_data in slide_data['images']:
                    try:
                        response = requests.get(img_data['url'], stream=True)
                        response.raise_for_status()
                        image_stream = io.BytesIO(response.content)

                        placeholder_idx = img_data.get('placeholder_idx', 2)
                        placeholder = slide.placeholders[placeholder_idx]
                        placeholder.insert_picture(image_stream)
                    except Exception as e:
                        print(f"Fehler beim Hinzufügen des Bildes: {e}")

            # Tabellen in Platzhalter einfügen
            if 'tables' in slide_data:
                for table_data in slide_data['tables']:
                    try:
                        placeholder_idx = table_data.get('placeholder_idx', 3)
                        placeholder = slide.placeholders[placeholder_idx]

                        rows = len(table_data['data'])
                        cols = len(table_data['data'][0])

                        table = placeholder.insert_table(rows, cols).table

                        for row_idx, row in enumerate(table_data['data']):
                            for col_idx, cell_data in enumerate(row):
                                table.cell(row_idx, col_idx).text = str(cell_data)
                    except Exception as e:
                        print(f"Fehler beim Hinzufügen der Tabelle: {e}")

            # Diagramme in Platzhalter einfügen
            if 'charts' in slide_data:
                for chart_data in slide_data['charts']:
                    try:
                        placeholder_idx = chart_data.get('placeholder_idx', 4)
                        placeholder = slide.placeholders[placeholder_idx]

                        chart_data_obj = CategoryChartData()
                        chart_data_obj.categories = chart_data.get('categories', [])

                        for series in chart_data.get('series', []):
                            chart_data_obj.add_series(series['name'], series['values'])

                        chart = placeholder.insert_chart(chart_data_obj).chart
                        chart.has_legend = True
                    except Exception as e:
                        print(f"Fehler beim Hinzufügen des Diagramms: {e}")

        # Closing Slide
        if 'closing_slide' in slides_data:
            closing_slide_data = slides_data['closing_slide']
            slide = prs.slides.add_slide(prs.slide_layouts[2])
            slide.shapes.title.text = escape_text(closing_slide_data.get('title', ''))
            slide.placeholders[1].text = escape_text(closing_slide_data.get('body', ''))

        # Speichern der Präsentation
        pptx_buffer = io.BytesIO()
        prs.save(pptx_buffer)
        pptx_buffer.seek(0)

        file_id = str(uuid.uuid4())
        file_path = f"/tmp/{file_id}.pptx"

        with open(file_path, 'wb') as f:
            f.write(pptx_buffer.getvalue())

        generated_files[file_id] = (file_path, time.time())
        download_link = url_for('download_file', file_id=file_id, _external=True)
        return jsonify({'download_link': download_link})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<file_id>')
def download_file(file_id):
    if file_id in generated_files:
        file_path, _ = generated_files[file_id]
        return send_file(
            file_path,
            mimetype='application/vnd.openxmlformats-officedocument.presentationml.presentation',
            download_name='generated_presentation.pptx',
            as_attachment=True
        )
    return "File not found", 404
