#!/usr/bin/env python3
"""
Flask API Server for OnlyFans Detector
Deploy this to make your detector accessible via HTTP for n8n integration
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import logging
from onlyfans_detector_v2 import detect_onlyfans_in_bio_link

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for n8n integration

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "OnlyFans Detector API",
        "version": "1.0.0"
    })

@app.route('/detect', methods=['POST'])
def detect_onlyfans():
    """Main detection endpoint"""
    try:
        # Get request data
        data = request.get_json()
        
        if not data or 'bio_link' not in data:
            return jsonify({
                "error": "Missing bio_link parameter",
                "usage": "Send POST with JSON: {\"bio_link\": \"https://link.me/username\"}"
            }), 400
        
        bio_link = data['bio_link']
        headless = data.get('headless', True)  # Default to headless
        
        logger.info(f"Processing bio link: {bio_link}")
        
        # Run detection (async function)
        result = asyncio.run(detect_onlyfans_in_bio_link(bio_link, headless))
        
        # Add request info to result
        result['request'] = {
            'bio_link': bio_link,
            'headless': headless
        }
        
        logger.info(f"Detection result: {result['has_onlyfans']} for {bio_link}")
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Detection error: {str(e)}")
        return jsonify({
            "error": "Detection failed",
            "message": str(e),
            "bio_link": data.get('bio_link') if 'data' in locals() else None
        }), 500

@app.route('/detect', methods=['GET'])
def detect_get():
    """GET endpoint for simple testing"""
    bio_link = request.args.get('bio_link')
    
    if not bio_link:
        return jsonify({
            "error": "Missing bio_link parameter",
            "usage": "GET /detect?bio_link=https://link.me/username"
        }), 400
    
    try:
        logger.info(f"Processing bio link (GET): {bio_link}")
        
        # Run detection
        result = asyncio.run(detect_onlyfans_in_bio_link(bio_link, headless=True))
        
        # Add request info
        result['request'] = {
            'bio_link': bio_link,
            'method': 'GET'
        }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Detection error (GET): {str(e)}")
        return jsonify({
            "error": "Detection failed",
            "message": str(e),
            "bio_link": bio_link
        }), 500

@app.route('/batch', methods=['POST'])
def batch_detect():
    """Batch detection endpoint for multiple bio links"""
    try:
        data = request.get_json()
        
        if not data or 'bio_links' not in data:
            return jsonify({
                "error": "Missing bio_links parameter",
                "usage": "Send POST with JSON: {\"bio_links\": [\"url1\", \"url2\"]}"
            }), 400
        
        bio_links = data['bio_links']
        headless = data.get('headless', True)
        
        if not isinstance(bio_links, list) or len(bio_links) == 0:
            return jsonify({
                "error": "bio_links must be a non-empty array"
            }), 400
        
        if len(bio_links) > 10:  # Limit batch size
            return jsonify({
                "error": "Maximum 10 bio links per batch"
            }), 400
        
        logger.info(f"Processing batch of {len(bio_links)} bio links")
        
        results = []
        for bio_link in bio_links:
            try:
                result = asyncio.run(detect_onlyfans_in_bio_link(bio_link, headless))
                result['bio_link'] = bio_link
                results.append(result)
            except Exception as e:
                results.append({
                    "bio_link": bio_link,
                    "has_onlyfans": False,
                    "error": str(e)
                })
        
        return jsonify({
            "batch_results": results,
            "total_processed": len(results),
            "successful": len([r for r in results if 'error' not in r])
        })
        
    except Exception as e:
        logger.error(f"Batch detection error: {str(e)}")
        return jsonify({
            "error": "Batch detection failed",
            "message": str(e)
        }), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found",
        "available_endpoints": [
            "GET /health",
            "GET /detect?bio_link=URL",
            "POST /detect",
            "POST /batch"
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error",
        "message": "Something went wrong on our end"
    }), 500

if __name__ == '__main__':
    # Development server
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
