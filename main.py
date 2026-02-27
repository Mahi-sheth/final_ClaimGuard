from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from flask_cors import CORS
import PyPDF2
import re
import hashlib
from datetime import datetime, timedelta
import io
import os
import json
from functools import wraps
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
import secrets
from werkzeug.utils import secure_filename
import base64
import sqlite3
from contextlib import closing

# Configuration
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')

# App Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'pdf'}
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)
app.config['DATABASE'] = 'claimguard.db'

# Create necessary directories
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('static', exist_ok=True)
os.makedirs('static/css', exist_ok=True)
os.makedirs('static/js', exist_ok=True)
os.makedirs('static/images', exist_ok=True)

CORS(app)

# Database functions
def get_db():
    """Get database connection"""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Initialize database tables"""
    with closing(get_db()) as db:
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

def init_db_schema():
    """Create database schema if not exists"""
    with closing(get_db()) as db:
        # Create users table
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create policies table
        db.execute('''
            CREATE TABLE IF NOT EXISTS policies (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                upload_time TIMESTAMP NOT NULL,
                policy_type TEXT NOT NULL,
                detected_type TEXT,
                policy_number TEXT,
                sum_insured TEXT,
                premium TEXT,
                issue_date TEXT,
                expiry_date TEXT,
                benefits TEXT,
                exclusions TEXT,
                clauses TEXT,
                risks TEXT,
                coverage TEXT,
                quality_metrics TEXT,
                coverage_risk INTEGER,
                cost_risk INTEGER,
                delay_risk INTEGER,
                overall_risk REAL,
                co_pay_percentage INTEGER,
                deductible INTEGER,
                room_rent_cap TEXT,
                sub_limits TEXT,
                text_length INTEGER,
                page_count INTEGER,
                file_path TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        db.commit()

# Initialize database on startup
init_db_schema()

def get_user_id(phone, name):
    """Get or create user and return user_id"""
    with closing(get_db()) as db:
        # Check if user exists
        cursor = db.execute('SELECT id FROM users WHERE phone = ?', (phone,))
        user = cursor.fetchone()
        
        if user:
            return user['id']
        else:
            # Create new user
            cursor = db.execute(
                'INSERT INTO users (name, phone) VALUES (?, ?)',
                (name, phone)
            )
            db.commit()
            return cursor.lastrowid

def save_policy_to_db(user_id, policy_data, file_path):
    """Save analyzed policy to database"""
    with closing(get_db()) as db:
        db.execute('''
            INSERT INTO policies (
                id, user_id, filename, upload_time, policy_type, detected_type,
                policy_number, sum_insured, premium, issue_date, expiry_date,
                benefits, exclusions, clauses, risks, coverage, quality_metrics,
                coverage_risk, cost_risk, delay_risk, overall_risk,
                co_pay_percentage, deductible, room_rent_cap, sub_limits,
                text_length, page_count, file_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            policy_data['id'],
            user_id,
            policy_data['filename'],
            policy_data['upload_time'],
            policy_data['policy_type'],
            policy_data.get('detected_type', ''),
            policy_data['policy_number'],
            policy_data['sum_insured'],
            policy_data['premium'],
            policy_data.get('key_dates', {}).get('issue_date', ''),
            policy_data.get('key_dates', {}).get('expiry_date', ''),
            json.dumps(policy_data.get('benefits', [])),
            json.dumps(policy_data.get('exclusions', [])),
            json.dumps(policy_data.get('clauses', {})),
            json.dumps(policy_data.get('risks', [])),
            json.dumps(policy_data.get('coverage', {})),
            json.dumps(policy_data.get('quality_metrics', {})),
            policy_data['risk_scores']['coverage_risk'],
            policy_data['risk_scores']['cost_risk'],
            policy_data['risk_scores']['delay_risk'],
            policy_data['risk_scores']['overall_risk'],
            policy_data['financial_details']['co_pay_percentage'],
            policy_data['financial_details']['deductible'],
            policy_data['financial_details']['room_rent_cap'],
            json.dumps(policy_data['financial_details']['sub_limits']),
            policy_data['text_length'],
            policy_data['page_count'],
            file_path
        ))
        db.commit()

def get_user_policies(user_id, limit=10):
    """Get policies for a specific user"""
    with closing(get_db()) as db:
        cursor = db.execute('''
            SELECT * FROM policies 
            WHERE user_id = ? 
            ORDER BY upload_time DESC 
            LIMIT ?
        ''', (user_id, limit))
        
        policies = []
        for row in cursor.fetchall():
            policy = dict(row)
            # Parse JSON fields
            policy['benefits'] = json.loads(policy['benefits']) if policy['benefits'] else []
            policy['exclusions'] = json.loads(policy['exclusions']) if policy['exclusions'] else []
            policy['clauses'] = json.loads(policy['clauses']) if policy['clauses'] else {}
            policy['risks'] = json.loads(policy['risks']) if policy['risks'] else []
            policy['coverage'] = json.loads(policy['coverage']) if policy['coverage'] else {}
            policy['quality_metrics'] = json.loads(policy['quality_metrics']) if policy['quality_metrics'] else {}
            policy['sub_limits'] = json.loads(policy['sub_limits']) if policy['sub_limits'] else {}
            
            # Reconstruct risk_scores
            policy['risk_scores'] = {
                'coverage_risk': policy['coverage_risk'],
                'cost_risk': policy['cost_risk'],
                'delay_risk': policy['delay_risk'],
                'overall_risk': policy['overall_risk']
            }
            
            # Reconstruct financial_details
            policy['financial_details'] = {
                'co_pay_percentage': policy['co_pay_percentage'],
                'deductible': policy['deductible'],
                'room_rent_cap': policy['room_rent_cap'],
                'sub_limits': policy['sub_limits']
            }
            
            # Reconstruct key_dates
            policy['key_dates'] = {
                'issue_date': policy['issue_date'],
                'expiry_date': policy['expiry_date']
            }
            
            policies.append(policy)
        
        return policies

def get_policy_by_id(policy_id, user_id):
    """Get specific policy for a user"""
    with closing(get_db()) as db:
        cursor = db.execute('''
            SELECT * FROM policies 
            WHERE id = ? AND user_id = ?
        ''', (policy_id, user_id))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        policy = dict(row)
        # Parse JSON fields
        policy['benefits'] = json.loads(policy['benefits']) if policy['benefits'] else []
        policy['exclusions'] = json.loads(policy['exclusions']) if policy['exclusions'] else []
        policy['clauses'] = json.loads(policy['clauses']) if policy['clauses'] else {}
        policy['risks'] = json.loads(policy['risks']) if policy['risks'] else []
        policy['coverage'] = json.loads(policy['coverage']) if policy['coverage'] else {}
        policy['quality_metrics'] = json.loads(policy['quality_metrics']) if policy['quality_metrics'] else {}
        policy['sub_limits'] = json.loads(policy['sub_limits']) if policy['sub_limits'] else {}
        
        # Reconstruct risk_scores
        policy['risk_scores'] = {
            'coverage_risk': policy['coverage_risk'],
            'cost_risk': policy['cost_risk'],
            'delay_risk': policy['delay_risk'],
            'overall_risk': policy['overall_risk']
        }
        
        # Reconstruct financial_details
        policy['financial_details'] = {
            'co_pay_percentage': policy['co_pay_percentage'],
            'deductible': policy['deductible'],
            'room_rent_cap': policy['room_rent_cap'],
            'sub_limits': policy['sub_limits']
        }
        
        # Reconstruct key_dates
        policy['key_dates'] = {
            'issue_date': policy['issue_date'],
            'expiry_date': policy['expiry_date']
        }
        
        return policy

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('landing_page'))
        return f(*args, **kwargs)
    return decorated_function

class RiskPredictor:
    """ML-based risk prediction model"""
    
    @staticmethod
    def extract_features(text):
        """Extract numerical features from text"""
        text_lower = text.lower()
        features = {}
        
        # 1. Count specific keywords (each gives different weight)
        keywords = {
            'waiting_period': ['waiting period', 'waiting time', 'cooling period'],
            'exclusion': ['exclusion', 'not covered', 'excluded', 'not payable'],
            'co_pay': ['co-pay', 'copay', 'coinsurance', 'payable by insured'],
            'sub_limit': ['sub-limit', 'sublimit', 'cap of', 'maximum limit'],
            'room_rent': ['room rent', 'room charges', 'accommodation'],
            'pre_existing': ['pre-existing', 'preexisting', 'existing condition'],
            'claim_days': ['within 24 hours', 'within 48 hours', 'immediately'],
            'deductible': ['deductible', 'excess amount', 'first pay'],
            'disease': ['cancer', 'diabetes', 'heart', 'kidney', 'liver', 'hiv'],
            'surgery': ['surgery', 'operation', 'procedure', 'treatment'],
            'hospital': ['hospital', 'medical', 'healthcare', 'clinic'],
            'percentage': ['%', 'percent', 'percentage'],
            'money': ['rupees', 'rs', 'inr', 'lakh', 'thousand'],
            'time': ['day', 'days', 'month', 'months', 'year', 'years'],
            'limit': ['limit', 'capped', 'maximum', 'upto']
        }
        
        for key, words in keywords.items():
            count = sum(text_lower.count(word) for word in words)
            features[key] = count
        
        # 2. Find percentages
        percentages = re.findall(r'(\d+)%', text_lower)
        features['avg_percentage'] = np.mean([int(p) for p in percentages]) if percentages else 0
        
        # 3. Find monetary values
        amounts = re.findall(r'rs\.?\s*(\d+)|₹\s*(\d+)', text_lower)
        flat_amounts = []
        for match in amounts:
            for val in match:
                if val:
                    flat_amounts.append(int(val))
        features['avg_amount'] = np.mean(flat_amounts) if flat_amounts else 0
        
        # 4. Find time periods
        days = re.findall(r'(\d+)\s*(day|days)', text_lower)
        months = re.findall(r'(\d+)\s*(month|months)', text_lower)
        years = re.findall(r'(\d+)\s*(year|years)', text_lower)
        
        features['has_days'] = len(days)
        features['has_months'] = len(months)
        features['has_years'] = len(years)
        
        # 5. Document complexity (longer = more complex = higher risk)
        features['length'] = min(len(text) / 1000, 10)  # Normalize
        
        return features
    
    @staticmethod
    def predict_risk(text, policy_type, age, has_disease):
        """Predict risk scores based on document features"""
        features = RiskPredictor.extract_features(text)
        
        # Coverage Risk (based on exclusions, waiting periods, disease mentions)
        coverage_risk = 20  # Base
        
        coverage_risk += features['waiting_period'] * 8
        coverage_risk += features['exclusion'] * 10
        coverage_risk += features['pre_existing'] * 12
        coverage_risk += features['disease'] * 5
        coverage_risk += features['has_years'] * 5
        
        # Adjust by policy type
        if policy_type == "Health Insurance":
            coverage_risk += 10  # Health policies have more exclusions
        elif policy_type == "Car Insurance":
            coverage_risk -= 10
        elif policy_type == "Life Insurance":
            coverage_risk -= 5
        
        # Cost Risk (based on co-pay, sub-limits, percentages)
        cost_risk = 15  # Base
        
        cost_risk += features['co_pay'] * 12
        cost_risk += features['sub_limit'] * 10
        cost_risk += features['room_rent'] * 8
        cost_risk += features['percentage'] * 5
        cost_risk += features['money'] * 3
        cost_risk += features['deductible'] * 10
        
        # Add percentage impact
        cost_risk += features['avg_percentage'] * 1.5
        
        # Delay Risk (based on claim conditions, time limits)
        delay_risk = 10  # Base
        
        delay_risk += features['claim_days'] * 15
        delay_risk += features['time'] * 4
        delay_risk += features['has_days'] * 8
        delay_risk += features['has_months'] * 5
        
        # Add user profile impact
        if age > 60:
            coverage_risk += 15
            delay_risk += 10
        elif age > 45:
            coverage_risk += 8
            delay_risk += 5
        
        if has_disease:
            coverage_risk += 20
            cost_risk += 10
        
        # Ensure within 0-100
        coverage_risk = min(max(int(coverage_risk), 0), 100)
        cost_risk = min(max(int(cost_risk), 0), 100)
        delay_risk = min(max(int(delay_risk), 0), 100)
        
        return {
            'coverage_risk': coverage_risk,
            'cost_risk': cost_risk,
            'delay_risk': delay_risk
        }
    
    @staticmethod
    def extract_co_pay_percentage(text):
        """Extract co-pay percentage from policy text"""
        text_lower = text.lower()
        
        patterns = [
            r'co[-\s]?pay[:\s]*(\d+)%',
            r'copayment[:\s]*(\d+)%',
            r'co[-\s]?insurance[:\s]*(\d+)%',
            r'payable by insured[:\s]*(\d+)%',
            r'(\d+)%\s*co[-\s]?pay',
            r'(\d+)%\s*copayment',
            r'(\d+)%\s*co-insurance'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return int(match.group(1))
        
        # Check for generic mentions of co-pay without percentage
        if 'co-pay' in text_lower or 'copay' in text_lower or 'co-payment' in text_lower:
            return 10  # Default if co-pay exists but no percentage mentioned
        
        return 0
    
    @staticmethod
    def extract_deductible(text):
        """Extract deductible amount from policy text"""
        text_lower = text.lower()
        
        patterns = [
            r'deductible[:\s]*rs\.?\s*(\d+)|deductible[:\s]*₹\s*(\d+)',
            r'excess[:\s]*rs\.?\s*(\d+)|excess[:\s]*₹\s*(\d+)',
            r'first pay[:\s]*rs\.?\s*(\d+)|first pay[:\s]*₹\s*(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                for val in match.groups():
                    if val:
                        return int(val)
        
        return 0
    
    @staticmethod
    def extract_room_rent_cap(text):
        """Extract room rent capping from policy text"""
        text_lower = text.lower()
        
        patterns = [
            r'room rent[:\s]*rs\.?\s*(\d+)|room rent[:\s]*₹\s*(\d+)',
            r'room charges[:\s]*rs\.?\s*(\d+)|room charges[:\s]*₹\s*(\d+)',
            r'accommodation[:\s]*rs\.?\s*(\d+)|accommodation[:\s]*₹\s*(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                for val in match.groups():
                    if val:
                        return val
        
        # Check for percentage-based room rent capping
        percent_match = re.search(r'room rent[:\s]*(\d+)%', text_lower)
        if percent_match:
            return percent_match.group(1) + "%"
        
        return None
    
    @staticmethod
    def extract_sub_limits(text):
        """Extract various sub-limits from policy text"""
        text_lower = text.lower()
        sub_limits = {}
        
        # Common sub-limits
        limit_types = {
            'icu': r'icu[:\s]*rs\.?\s*(\d+)|icu[:\s]*₹\s*(\d+)',
            'surgery': r'surgery[:\s]*rs\.?\s*(\d+)|surgery[:\s]*₹\s*(\d+)',
            'doctor': r'doctor[:\s]*rs\.?\s*(\d+)|doctor[:\s]*₹\s*(\d+)',
            'medicine': r'medicine[:\s]*rs\.?\s*(\d+)|medicine[:\s]*₹\s*(\d+)',
            'diagnostic': r'diagnostic[:\s]*rs\.?\s*(\d+)|diagnostic[:\s]*₹\s*(\d+)'
        }
        
        for limit_type, pattern in limit_types.items():
            match = re.search(pattern, text_lower)
            if match:
                for val in match.groups():
                    if val:
                        sub_limits[limit_type] = int(val)
        
        return sub_limits

class PolicyAnalyzer:
    """Enhanced policy analysis engine"""
    
    # Comprehensive policy type database
    POLICY_TYPES = {
        "Health Insurance": {
            'keywords': ['health', 'medical', 'hospital', 'surgery', 'disease', 'treatment', 'doctor', 
                        'medicine', 'clinical', 'diagnosis', 'patient', 'healthcare', 'policy', 'insurance', 
                        'cover', 'benefits', 'cashless', 'reimbursement', 'room rent', 'icu', 'pre-existing',
                        'waiting period', 'copay', 'day care', 'hospitalization'],
            'weight': 1.5,
            'color': '#FF6B6B',
            'icon': '🏥'
        },
        "Car Insurance": {
            'keywords': ['car', 'vehicle', 'motor', 'automobile', 'accident', 'drive', 'driver', 'collision', 
                        'repair', 'garage', 'road', 'traffic', 'third party', 'comprehensive', 'own damage',
                        'theft', 'liability', 'no claim bonus', 'depreciation', 'towing', 'tire', 'engine'],
            'weight': 1.5,
            'color': '#4ECDC4',
            'icon': '🚗'
        },
        "Life Insurance": {
            'keywords': ['life', 'death', 'term', 'maturity', 'nominee', 'beneficiary', 'assured', 'policyholder', 
                        'premium', 'sum assured', 'survival', 'mortality', 'endowment', 'whole life', 'riders',
                        'critical illness', 'accidental death', 'disability', 'income benefit'],
            'weight': 1.5,
            'color': '#45B7D1',
            'icon': '💚'
        },
        "Travel Insurance": {
            'keywords': ['travel', 'trip', 'flight', 'baggage', 'overseas', 'foreign', 'passport', 'journey', 
                        'tour', 'abroad', 'holiday', 'vacation', 'airline', 'trip cancellation', 'delay',
                        'lost luggage', 'emergency evacuation', 'travel assistance'],
            'weight': 1.5,
            'color': '#96CEB4',
            'icon': '✈️'
        },
        "Home Insurance": {
            'keywords': ['home', 'house', 'property', 'building', 'contents', 'fire', 'theft', 'flood', 
                        'earthquake', 'residence', 'household', 'structure', 'burglary', 'natural disaster',
                        'personal belongings', 'liability', 'renovation'],
            'weight': 1.5,
            'color': '#FFE194',
            'icon': '🏠'
        },
        "Bike Insurance": {
            'keywords': ['bike', 'motorcycle', 'two wheeler', 'scooter', 'helmet', 'rider', 'biking', 
                        'motorcycling', 'two-wheeler', 'accessories', 'pillion', 'comprehensive'],
            'weight': 1.5,
            'color': '#D4A5A5',
            'icon': '🏍️'
        }
    }
    
    @staticmethod
    def extract_policy_type(text):
        """Enhanced policy type detection with confidence scoring"""
        text_lower = text.lower()
        
        scores = {}
        keyword_matches = defaultdict(list)
        
        for p_type, data in PolicyAnalyzer.POLICY_TYPES.items():
            score = 0
            for keyword in data['keywords']:
                count = text_lower.count(keyword)
                if count > 0:
                    score += count * data['weight']
                    keyword_matches[p_type].append(keyword)
            scores[p_type] = score
        
        # Sort by score
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        # Calculate confidence
        total_score = sum(scores.values()) or 1
        results = []
        
        for p_type, score in sorted_scores:
            confidence = (score / total_score) * 100
            if confidence > 5:  # Only include meaningful matches
                results.append({
                    'type': p_type,
                    'confidence': round(confidence, 1),
                    'score': score,
                    'matched_keywords': keyword_matches[p_type][:5]  # Top 5 keywords
                })
        
        return results
    
    @staticmethod
    def extract_sum_insured(text):
        """Extract sum insured with multiple patterns"""
        text_lower = text.lower()
        
        patterns = [
            r'(?:sum\s*insured|cover|coverage|sum\s*assured)[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:lakh|lac|crore|million|thousand)?',
            r'(?:policy\s*amount|cover\s*amount|benefit\s*amount)[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
            r'(?:liability|maximum\s*benefit)[:\s]*(?:of)?\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
            r'up\s*to\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
            r'cover\s*of\s*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                amount = match.group(1).replace(',', '')
                # Check for lakh/crore suffixes
                suffix_match = re.search(r'(?:lakh|lac|crore|million|thousand)', text_lower[match.end():match.end()+10])
                if suffix_match:
                    suffix = suffix_match.group()
                    if 'lakh' in suffix or 'lac' in suffix:
                        amount = str(float(amount) * 100000)
                    elif 'crore' in suffix:
                        amount = str(float(amount) * 10000000)
                    elif 'million' in suffix:
                        amount = str(float(amount) * 1000000)
                    elif 'thousand' in suffix:
                        amount = str(float(amount) * 1000)
                return amount
        
        return "Not specified"
    
    @staticmethod
    def extract_premium(text):
        """Extract premium amount with multiple patterns"""
        text_lower = text.lower()
        
        patterns = [
            r'(?:premium|annual\s*premium|yearly\s*premium)[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
            r'(?:policy\s*fee|installment|payment)[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)',
            r'(?:pay|payable|charged)[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)\s*(?:per\s*annum|annually|yearly)',
            r'premium\s*amount[:\s]*(?:rs\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                return match.group(1).replace(',', '')
        
        return "Not specified"
    
    @staticmethod
    def extract_key_dates(text):
        """Extract important policy dates"""
        text_lower = text.lower()
        dates = {}
        
        # Policy issue date
        issue_patterns = [
            r'(?:policy\s*issued?|date\s*of\s*issue|issued?\s*on)[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(?:commencement|commencing|start)[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
        ]
        
        for pattern in issue_patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                dates['issue_date'] = match.group(1)
                break
        
        # Expiry date
        expiry_patterns = [
            r'(?:expir|valid|validity|expiry)[:\s]*(?:date)?[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(?:valid\s*until|expires?\s*on)[:\s]*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})'
        ]
        
        for pattern in expiry_patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                dates['expiry_date'] = match.group(1)
                break
        
        return dates
    
    @staticmethod
    def extract_benefits(text):
        """Extract key benefits from policy"""
        text_lower = text.lower()
        benefits = []
        
        benefit_keywords = [
            (r'(?:covers?|coverage\s*for|benefit\s*of)\s+([^.]{10,50})\.', 'coverage'),
            (r'(?:includes?|inclusions?)[:\s]+([^.]{10,50})\.', 'inclusion'),
            (r'(?:provides?|offer|offering)[:\s]+([^.]{10,50})\.', 'benefit')
        ]
        
        for pattern, benefit_type in benefit_keywords:
            matches = re.findall(pattern, text_lower, re.I)
            for match in matches[:3]:  # Limit per type
                if len(match) > 15 and match not in [b['text'] for b in benefits]:
                    benefits.append({
                        'text': match.strip().capitalize(),
                        'type': benefit_type
                    })
        
        return benefits[:8]  # Return top 8 benefits
    
    @staticmethod
    def extract_exclusions(text):
        """Enhanced exclusion extraction"""
        text_lower = text.lower()
        exclusions = []
        
        exclusion_patterns = [
            r'(?:not\s+cover(?:ed)?|exclusion|excluded)[^.]*\.',
            r'(?:will\s+not\s+pay|not\s+liable)[^.]*\.',
            r'(?:does\s+not\s+apply|not\s+included)[^.]*\.',
            r'(?:limitations?|restrictions?)[^.]*\.',
            r'(?:waiting\s+period)[^.]*\.',
            r'(?:pre-existing\s+condition)[^.]*\.'
        ]
        
        for pattern in exclusion_patterns:
            matches = re.findall(pattern, text_lower, re.I)
            for match in matches:
                clean_match = match.strip()
                # Clean up the text
                clean_match = re.sub(r'\s+', ' ', clean_match)
                if len(clean_match) > 15 and clean_match not in exclusions:
                    exclusions.append(clean_match.capitalize())
        
        return list(dict.fromkeys(exclusions))[:8]  # Remove duplicates, keep 8
    
    @staticmethod
    def extract_key_clauses(text):
        """Extract key clauses from policy text"""
        text_lower = text.lower()
        clauses = {}
        
        terms = {
            "waiting period": r'waiting[-\s]?period|waiting\s+time|pre[-\s]?existing\s+waiting',
            "exclusion": r'exclusion|not\s+cover|will\s+not\s+cover|excluded|not\s+payable',
            "co-pay": r'co[-\s]?pay|copayment|co-payment|coinsurance',
            "sub-limit": r'sub[-\s]?limit|sublimit|limit\s+of\s+coverage|cap\s+of',
            "room rent": r'room\s+rent|room\s+charges|accommodation\s+benefit',
            "pre-existing": r'pre[-\s]?existing|preexisting|known\s+condition',
            "claim": r'claim\s+process|claim\s+filing|intimation|claim\s+settlement',
            "deductible": r'deductible|excess|first\s+pay'
        }
        
        for term, pattern in terms.items():
            sentences = [s for s in text.split('.') if re.search(pattern, s.lower())]
            if sentences:
                clauses[term] = sentences[0].strip() + "."
            else:
                clauses[term] = "Not mentioned in document"
        
        return clauses
    
    @staticmethod
    def analyze_policy_quality(text):
        """Analyze policy quality metrics"""
        text_lower = text.lower()
        
        metrics = {
            'clarity': 0,
            'comprehensiveness': 0,
            'transparency': 0
        }
        
        # Clarity indicators
        clarity_indicators = [
            'clear', 'simple', 'understand', 'easy', 'plain',
            'explain', 'described', 'definition', 'meaning'
        ]
        clarity_score = sum(text_lower.count(ind) for ind in clarity_indicators)
        metrics['clarity'] = min(100, clarity_score * 10)
        
        # Comprehensiveness indicators
        comprehensive_indicators = [
            'comprehensive', 'complete', 'full', 'extensive', 'broad',
            'wide', 'range', 'variety', 'multiple', 'various'
        ]
        comprehensive_score = sum(text_lower.count(ind) for ind in comprehensive_indicators)
        metrics['comprehensiveness'] = min(100, comprehensive_score * 10)
        
        # Transparency indicators
        transparency_indicators = [
            'transparent', 'disclose', 'disclosure', 'clear', 'explicit',
            'specifically', 'detailed', 'details', 'specific', 'particular'
        ]
        transparency_score = sum(text_lower.count(ind) for ind in transparency_indicators)
        metrics['transparency'] = min(100, transparency_score * 10)
        
        return metrics
    
    @staticmethod
    def analyze_risk_factors(text, age, disease):
        """Enhanced risk analysis"""
        text_lower = text.lower()
        risk_factors = []
        
        # Age factor with detailed analysis
        if age > 60:
            risk_factors.append({
                "factor": "Age", 
                "impact": "High", 
                "score": 85,
                "description": "Age above 60 significantly increases claim scrutiny and premium",
                "recommendation": "Consider policies with lower age restrictions or senior citizen plans"
            })
        elif age > 50:
            risk_factors.append({
                "factor": "Age", 
                "impact": "Medium-High", 
                "score": 65,
                "description": "Age between 50-60 may affect premium and coverage options",
                "recommendation": "Review age-related clauses and premium loading carefully"
            })
        elif age > 40:
            risk_factors.append({
                "factor": "Age", 
                "impact": "Medium", 
                "score": 45,
                "description": "Moderate age-related risk factors to consider",
                "recommendation": "Standard age-related considerations apply"
            })
        
        # Disease factor with detailed analysis
        if disease and disease.lower() != 'none':
            disease_lower = disease.lower()
            if any(term in disease_lower for term in ['diabetes', 'blood pressure', 'heart', 'cancer', 'thyroid']):
                risk_factors.append({
                    "factor": "Pre-existing condition", 
                    "impact": "Critical", 
                    "score": 90,
                    "description": f"History of {disease} will significantly impact coverage and may have long waiting periods",
                    "recommendation": "Look for policies with shorter waiting periods for pre-existing conditions"
                })
            else:
                risk_factors.append({
                    "factor": "Pre-existing condition", 
                    "impact": "High", 
                    "score": 75,
                    "description": f"History of {disease} may affect coverage and require waiting periods",
                    "recommendation": "Check waiting period clauses and sub-limits for this condition"
                })
        
        # Exclusion analysis
        exclusion_count = len(re.findall(r'exclusion|not\s+cover|excluded', text_lower))
        if exclusion_count > 8:
            risk_factors.append({
                "factor": "High exclusion count", 
                "impact": "High", 
                "score": 80,
                "description": f"Policy contains {exclusion_count} exclusion-related terms - higher than average",
                "recommendation": "Review all exclusions carefully; consider if coverage gaps exist"
            })
        elif exclusion_count > 4:
            risk_factors.append({
                "factor": "Moderate exclusions", 
                "impact": "Medium", 
                "score": 50,
                "description": f"Policy contains {exclusion_count} exclusion-related terms",
                "recommendation": "Understand key exclusions that may affect your specific needs"
            })
        
        # Waiting period analysis
        waiting_period = PolicyAnalyzer.extract_waiting_period(text)
        if "year" in waiting_period.lower():
            years = re.search(r'(\d+)', waiting_period)
            if years and int(years.group(1)) > 2:
                risk_factors.append({
                    "factor": "Long waiting period", 
                    "impact": "High", 
                    "score": 75,
                    "description": f"Long waiting period of {waiting_period} before full coverage applies",
                    "recommendation": "Consider if you can wait this period for claims; check for shorter alternatives"
                })
        elif "month" in waiting_period.lower():
            risk_factors.append({
                "factor": "Waiting period applies", 
                "impact": "Medium", 
                "score": 40,
                "description": f"Waiting period of {waiting_period} applies for certain conditions",
                "recommendation": "Plan healthcare needs around the waiting period"
            })
        
        # Co-pay analysis
        copay = RiskPredictor.extract_co_pay_percentage(text)
        if copay > 30:
            risk_factors.append({
                "factor": "Very high co-pay", 
                "impact": "Critical", 
                "score": 90,
                "description": f"High co-pay of {copay}% means significant out-of-pocket expenses",
                "recommendation": "Consider policies with lower co-pay or build savings for co-pay amount"
            })
        elif copay > 20:
            risk_factors.append({
                "factor": "High co-pay", 
                "impact": "High", 
                "score": 70,
                "description": f"Co-pay of {copay}% requires substantial out-of-pocket payment",
                "recommendation": "Budget for co-pay amounts and check if co-pay applies to all claims"
            })
        elif copay > 10:
            risk_factors.append({
                "factor": "Moderate co-pay", 
                "impact": "Medium", 
                "score": 40,
                "description": f"Co-pay of {copay}% applies",
                "recommendation": "Standard co-pay arrangement; plan for this expense"
            })
        
        # Deductible analysis
        deductible = RiskPredictor.extract_deductible(text)
        if deductible > 50000:
            risk_factors.append({
                "factor": "High deductible", 
                "impact": "High", 
                "score": 75,
                "description": f"Deductible of ₹{deductible:,} must be paid before coverage starts",
                "recommendation": "Ensure you have funds available for the deductible amount"
            })
        elif deductible > 10000:
            risk_factors.append({
                "factor": "Moderate deductible", 
                "impact": "Medium", 
                "score": 45,
                "description": f"Deductible of ₹{deductible:,} applies per claim",
                "recommendation": "Plan for this out-of-pocket expense per claim"
            })
        
        return risk_factors
    
    @staticmethod
    def extract_waiting_period(text):
        """Enhanced waiting period extraction"""
        text_lower = text.lower()
        
        patterns = [
            r'waiting\s*period\s*(?:of)?\s*(\d+)\s*(day|days|month|months|year|years)',
            r'(\d+)\s*(day|days|month|months|year|years)\s+waiting\s*period',
            r'initial\s+waiting\s+period\s*(?:of)?\s*(\d+)\s*(day|days|month|months|year|years)?',
            r'waiting\s+period\s+applicable\s*(?:for)?\s*(\d+)\s*(day|days|month|months|year|years)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.I)
            if match:
                if len(match.groups()) == 2:
                    return f"{match.group(1)} {match.group(2)}"
                else:
                    return f"{match.group(1)} months" if match.group(1) else "Initial period applies"
        
        # Check if waiting period mentioned but no duration
        if 'waiting period' in text_lower:
            return "Mentioned (duration not specified)"
        
        return "Not specified"
    
    @staticmethod
    def calculate_risk_score(age, disease, risk_factors, coverage, ml_risks):
        """Calculate comprehensive risk score using ML predictions"""
        # Use ML predicted risks as base
        coverage_risk = ml_risks.get('coverage_risk', 50)
        cost_risk = ml_risks.get('cost_risk', 50)
        delay_risk = ml_risks.get('delay_risk', 50)
        
        # Weighted average for overall risk
        overall_risk = (coverage_risk * 0.4 + cost_risk * 0.35 + delay_risk * 0.25)
        
        return {
            'coverage_risk': coverage_risk,
            'cost_risk': cost_risk,
            'delay_risk': delay_risk,
            'overall_risk': round(overall_risk, 1)
        }

class VisualizationGenerator:
    """Generate professional visualizations for policy analysis"""
    
    @staticmethod
    def create_risk_pie_chart(ml_risks):
        """Create a pie chart showing ML-based risk distribution"""
        fig, ax = plt.subplots(figsize=(8, 6))
        
        labels = ['Coverage Risk', 'Out-of-Pocket Risk', 'Delay Risk']
        values = [
            ml_risks.get('coverage_risk', 0),
            ml_risks.get('cost_risk', 0),
            ml_risks.get('delay_risk', 0)
        ]
        colors_list = ['#FF6B6B', '#4ECDC4', '#45B7D1']
        
        wedges, texts, autotexts = ax.pie(values, labels=labels, autopct='%1.1f%%',
                                          colors=colors_list, startangle=90)
        ax.set_title('Claim Risk Breakdown', fontsize=16, fontweight='bold')
        
        # Save to bytes buffer
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()
        
        return img_buffer
    
    @staticmethod
    def create_risk_breakdown_pie_chart(risk_factors):
        """Create a pie chart showing risk factor breakdown by impact level"""
        if not risk_factors:
            return None
        
        # Count risks by impact level
        impact_counts = defaultdict(int)
        for risk in risk_factors:
            impact_counts[risk['impact']] += 1
        
        # Prepare data
        labels = list(impact_counts.keys())
        sizes = list(impact_counts.values())
        
        # Color mapping for different impact levels
        color_map = {
            'Critical': '#FF0000',
            'High': '#FF6B6B',
            'Medium-High': '#FFA500',
            'Medium': '#FFD93D',
            'Low': '#6BCB77'
        }
        colors_list = [color_map.get(impact, '#808080') for impact in labels]
        
        # Create pie chart
        fig, ax = plt.subplots(figsize=(8, 8))
        wedges, texts, autotexts = ax.pie(sizes, labels=labels, colors=colors_list,
                                          autopct='%1.1f%%', startangle=90, shadow=True)
        
        # Customize text
        for text in texts:
            text.set_fontsize(10)
            text.set_fontweight('bold')
        for autotext in autotexts:
            autotext.set_fontsize(9)
            autotext.set_color('white')
            autotext.set_fontweight('bold')
        
        ax.set_title('Risk Factor Breakdown by Impact', fontsize=16, fontweight='bold', pad=20)
        ax.axis('equal')
        
        # Save to bytes buffer
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()
        
        return img_buffer
    
    @staticmethod
    def create_comparison_bar_chart(ml_risks):
        """Create a bar chart comparing policy vs industry average"""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        categories = ['Coverage', 'Out-of-Pocket', 'Delay']
        policy_values = [
            ml_risks.get('coverage_risk', 0),
            ml_risks.get('cost_risk', 0),
            ml_risks.get('delay_risk', 0)
        ]
        industry_avg = [45, 35, 25]  # Industry averages
        
        x = np.arange(len(categories))
        width = 0.35
        
        bars1 = ax.bar(x - width/2, policy_values, width, label='This Policy', color='#FF6B6B')
        bars2 = ax.bar(x + width/2, industry_avg, width, label='Industry Avg', color='#45B7D1', alpha=0.7)
        
        ax.set_ylabel('Risk Score (%)')
        ax.set_title('Policy vs Industry Average Comparison')
        ax.set_xticks(x)
        ax.set_xticklabels(categories)
        ax.legend()
        ax.set_ylim(0, 100)
        
        # Add value labels
        for bar in bars1:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{int(height)}%', ha='center', va='bottom')
        
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()
        
        return img_buffer
    
    @staticmethod
    def create_claim_impact_chart(claim_amount, insurance_pays, out_of_pocket):
        """Create a pie chart showing claim impact distribution"""
        fig, ax = plt.subplots(figsize=(8, 8))
        
        labels = ['Insurance Pays', 'You Pay']
        values = [insurance_pays, out_of_pocket]
        colors_list = ['#28a745', '#dc3545']
        
        wedges, texts, autotexts = ax.pie(values, labels=labels, autopct='%1.1f%%',
                                          colors=colors_list, startangle=90, explode=(0.05, 0.05))
        ax.set_title(f'Claim Impact Analysis - Total: ₹{claim_amount:,.0f}', fontsize=14, fontweight='bold')
        
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        img_buffer.seek(0)
        plt.close()
        
        return img_buffer

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def too_large_error(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413


# Routes
@app.route('/')
def landing_page():
    """Serve the landing page"""
    return send_file('index.html')

@app.route('/login')
def login_page():
    """Serve the login page"""
    # If already logged in, go to dashboard
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return send_file('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard after login"""
    return render_template('dashboard.html', user=session.get('user', {}))

@app.route('/api/login', methods=['POST'])
def login():
    """Handle login"""
    try:
        data = request.json
        if not data or 'name' not in data or 'phone' not in data:
            return jsonify({'success': False, 'error': 'Name and phone required'}), 400
        
        # Get or create user and get user_id
        user_id = get_user_id(data.get('phone'), data.get('name'))
        
        # Create session
        session.permanent = True
        session['user'] = {
            'id': user_id,
            'name': data.get('name'),
            'phone': data.get('phone'),
            'login_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/logout')
def logout():
    """Handle logout"""
    session.pop('user', None)
    return redirect(url_for('landing_page'))

@app.route('/api/analyze-policy', methods=['POST'])
@login_required
def analyze_policy():
    """Enhanced policy analysis with ML-based predictions"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        
        # Validate file
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Get form data
        age = int(request.form.get('age', 35))
        disease = request.form.get('disease', '')
        selected_type = request.form.get('policyType', 'Health Insurance')
        
        # Read PDF
        try:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ''
            for page in pdf_reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + ' '
        except Exception as e:
            return jsonify({'error': 'Could not read PDF file. Please ensure it is a valid PDF.'}), 400
        
        if not text.strip():
            return jsonify({'error': 'Could not extract text from PDF. The file might be scanned or image-based.'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        saved_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], saved_filename)
        file.seek(0)  # Reset file pointer
        file.save(file_path)
        
        # Detect policy type from PDF content
        text_lower = text.lower()
        type_keywords = {
            "Health Insurance": ['health', 'medical', 'hospital', 'surgery', 'disease', 'treatment', 'doctor', 'medicine', 'illness', 'diagnosis'],
            "Car Insurance": ['car', 'vehicle', 'motor', 'automobile', 'accident', 'drive', 'driver', 'collision', 'theft', 'damage'],
            "Life Insurance": ['life', 'death', 'term', 'maturity', 'nominee', 'assured', 'survival', 'beneficiary'],
            "Travel Insurance": ['travel', 'trip', 'flight', 'baggage', 'overseas', 'foreign', 'passport', 'visa', 'journey']
        }
        
        type_scores = {}
        for p_type, keywords in type_keywords.items():
            score = sum(text_lower.count(word) for word in keywords)
            type_scores[p_type] = score
        
        detected_type = max(type_scores, key=type_scores.get) if max(type_scores.values()) > 0 else "Unknown"
        
        # Extract key clauses
        clauses = PolicyAnalyzer.extract_key_clauses(text)
        
        # Extract financial details using RiskPredictor
        co_pay_percentage = RiskPredictor.extract_co_pay_percentage(text)
        deductible = RiskPredictor.extract_deductible(text)
        room_rent_cap = RiskPredictor.extract_room_rent_cap(text)
        sub_limits = RiskPredictor.extract_sub_limits(text)
        
        # Use ML to predict risk scores
        ml_risks = RiskPredictor.predict_risk(text, selected_type, age, bool(disease))
        
        # Extract all policy details
        policy_number = re.search(r'policy\s*(?:no|number)[:\s]*([A-Z0-9/-]+)', text, re.I)
        policy_number = policy_number.group(1) if policy_number else "Not found"
        
        sum_insured = PolicyAnalyzer.extract_sum_insured(text)
        premium = PolicyAnalyzer.extract_premium(text)
        key_dates = PolicyAnalyzer.extract_key_dates(text)
        benefits = PolicyAnalyzer.extract_benefits(text)
        exclusions = PolicyAnalyzer.extract_exclusions(text)
        
        # Coverage details
        coverage = {
            'comprehensive': "Yes" if "comprehensive" in text.lower() else "Limited/Specified",
            'waiting_period': PolicyAnalyzer.extract_waiting_period(text),
            'co_pay': f"{co_pay_percentage}%" if co_pay_percentage > 0 else "0%",
            'deductible': f"₹{deductible:,}" if deductible > 0 else "Not specified"
        }
        
        # Analyze risk factors
        risk_factors = PolicyAnalyzer.analyze_risk_factors(text, age, disease)
        
        # Calculate risk scores using ML
        risk_scores = PolicyAnalyzer.calculate_risk_score(age, disease, risk_factors, coverage, ml_risks)
        
        # Analyze quality metrics
        quality_metrics = PolicyAnalyzer.analyze_policy_quality(text)
        
        # Generate unique ID
        policy_id = hashlib.md5(f"{text}{datetime.now()}".encode()).hexdigest()[:16]
        
        # Prepare comprehensive result
        result = {
            'id': policy_id,
            'filename': filename,
            'upload_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'policy_type': selected_type,
            'detected_type': detected_type,
            'policy_number': policy_number,
            'sum_insured': sum_insured,
            'premium': premium,
            'key_dates': key_dates,
            'benefits': benefits,
            'exclusions': exclusions,
            'clauses': clauses,
            'risks': risk_factors,
            'coverage': coverage,
            'quality_metrics': quality_metrics,
            'risk_scores': risk_scores,
            'financial_details': {
                'co_pay_percentage': co_pay_percentage,
                'deductible': deductible,
                'room_rent_cap': room_rent_cap,
                'sub_limits': sub_limits
            },
            'text_length': len(text),
            'page_count': len(pdf_reader.pages),
            'unique_id': policy_id
        }
        
        # Save to database
        save_policy_to_db(session['user']['id'], result, file_path)
        
        # Generate visualizations
        visualizations = {}
        
        # Risk pie chart
        risk_chart = VisualizationGenerator.create_risk_pie_chart(risk_scores)
        if risk_chart:
            visualizations['risk_pie'] = base64.b64encode(risk_chart.getvalue()).decode('utf-8')
        
        # Risk breakdown pie chart
        risk_breakdown_chart = VisualizationGenerator.create_risk_breakdown_pie_chart(risk_factors)
        if risk_breakdown_chart:
            visualizations['risk_breakdown'] = base64.b64encode(risk_breakdown_chart.getvalue()).decode('utf-8')
        
        # Comparison bar chart
        comparison_chart = VisualizationGenerator.create_comparison_bar_chart(risk_scores)
        if comparison_chart:
            visualizations['comparison_chart'] = base64.b64encode(comparison_chart.getvalue()).decode('utf-8')
        
        return jsonify({
            'success': True,
            'policy': result,
            'visualizations': visualizations
        })
        
    except Exception as e:
        print(f"Analysis Error: {str(e)}")
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500

@app.route('/api/simulate-claim', methods=['POST'])
@login_required
def simulate_claim():
    """Simulate claim impact based on policy terms"""
    try:
        data = request.json
        policy_id = data.get('policy_id')
        claim_amount = float(data.get('claim_amount', 500000))
        
        # Find policy for this user
        policy = get_policy_by_id(policy_id, session['user']['id'])
        if not policy:
            return jsonify({'error': 'Policy not found'}), 404
        
        # Get policy-specific financial details
        financial = policy['financial_details']
        co_pay_pct = financial['co_pay_percentage']
        deductible = financial['deductible']
        
        # Calculate financial impact
        remaining_amount = claim_amount
        
        # 1. Apply deductible first
        if deductible > 0:
            deductible_amount = min(deductible, remaining_amount)
            remaining_amount -= deductible_amount
        else:
            deductible_amount = 0
        
        # 2. Apply co-pay
        if co_pay_pct > 0:
            co_pay_amount = remaining_amount * co_pay_pct / 100
            remaining_amount -= co_pay_amount
        else:
            co_pay_amount = 0
        
        # Insurance pays the remaining amount
        insurance_pays = remaining_amount
        out_of_pocket = claim_amount - insurance_pays
        
        # Generate claim impact chart
        claim_chart = VisualizationGenerator.create_claim_impact_chart(claim_amount, insurance_pays, out_of_pocket)
        
        return jsonify({
            'success': True,
            'simulation': {
                'claim_amount': claim_amount,
                'insurance_pays': round(insurance_pays),
                'out_of_pocket': round(out_of_pocket),
                'deductible_applied': deductible_amount,
                'copay_applied': round(co_pay_amount),
                'coverage_percentage': round((insurance_pays / claim_amount) * 100, 1)
            },
            'chart': base64.b64encode(claim_chart.getvalue()).decode('utf-8') if claim_chart else None
        })
        
    except Exception as e:
        print(f"Simulation Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/compare-policies', methods=['POST'])
@login_required
def compare_policies():
    """Compare multiple policies"""
    try:
        data = request.json
        policy_ids = data.get('policy_ids', [])
        
        if len(policy_ids) < 2:
            return jsonify({'error': 'At least 2 policies required for comparison'}), 400
        
        # Get selected policies for this user
        selected_policies = []
        for policy_id in policy_ids:
            policy = get_policy_by_id(policy_id, session['user']['id'])
            if policy:
                selected_policies.append(policy)
        
        if len(selected_policies) < 2:
            return jsonify({'error': 'Selected policies not found'}), 404
        
        # Prepare comparison data
        comparison = {
            'policies': selected_policies,
            'metrics': {
                'avg_coverage_risk': sum(p['risk_scores']['coverage_risk'] for p in selected_policies) / len(selected_policies),
                'avg_cost_risk': sum(p['risk_scores']['cost_risk'] for p in selected_policies) / len(selected_policies),
                'avg_delay_risk': sum(p['risk_scores']['delay_risk'] for p in selected_policies) / len(selected_policies),
                'min_overall': min(p['risk_scores']['overall_risk'] for p in selected_policies),
                'max_overall': max(p['risk_scores']['overall_risk'] for p in selected_policies)
            },
            'recommendation': None
        }
        
        # Generate recommendation
        best_policy = min(selected_policies, key=lambda x: x['risk_scores']['overall_risk'])
        comparison['recommendation'] = {
            'policy_id': best_policy['id'],
            'reason': f"Lowest overall risk score ({best_policy['risk_scores']['overall_risk']}%) with {len(best_policy.get('benefits', []))} key benefits"
        }
        
        return jsonify({
            'success': True,
            'comparison': comparison
        })
        
    except Exception as e:
        print(f"Comparison Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/policy-stats')
@login_required
def policy_stats():
    """Get policy statistics for dashboard"""
    try:
        # Get user's policies
        policies = get_user_policies(session['user']['id'], limit=100)
        
        stats = {
            'total_analyzed': len(policies),
            'avg_risk_score': 0,
            'policy_types': {},
            'risk_distribution': {
                'Low (0-30)': 0,
                'Moderate (31-60)': 0,
                'High (61-80)': 0,
                'Critical (81-100)': 0
            },
            'recent_activity': []
        }
        
        if policies:
            # Average risk score
            stats['avg_risk_score'] = round(sum(p['risk_scores']['overall_risk'] for p in policies) / len(policies), 1)
            
            # Policy type distribution
            type_counts = defaultdict(int)
            for policy in policies:
                type_counts[policy['policy_type']] += 1
            stats['policy_types'] = dict(type_counts)
            
            # Risk distribution
            for policy in policies:
                risk = policy['risk_scores']['overall_risk']
                if risk <= 30:
                    stats['risk_distribution']['Low (0-30)'] += 1
                elif risk <= 60:
                    stats['risk_distribution']['Moderate (31-60)'] += 1
                elif risk <= 80:
                    stats['risk_distribution']['High (61-80)'] += 1
                else:
                    stats['risk_distribution']['Critical (81-100)'] += 1
            
            # Recent activity
            for policy in policies[:5]:
                stats['recent_activity'].append({
                    'id': policy['id'],
                    'type': policy['policy_type'],
                    'risk': policy['risk_scores']['overall_risk'],
                    'time': policy['upload_time']
                })
        
        return jsonify(stats)
        
    except Exception as e:
        print(f"Stats Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-report/<policy_id>')
@login_required
def generate_report(policy_id):
    """Enhanced PDF report generation with charts"""
    try:
        # Find policy for this user
        policy = get_policy_by_id(policy_id, session['user']['id'])
        if not policy:
            return jsonify({'error': 'Policy not found'}), 404
        
        # Create PDF with ReportLab
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#0a1e32'),
            alignment=1,
            spaceAfter=30
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#0a1e32'),
            spaceAfter=12,
            spaceBefore=20
        )
        
        # Title
        story.append(Paragraph("ClaimGuard Professional Policy Analysis Report", title_style))
        story.append(Spacer(1, 20))
        
        # Executive Summary
        story.append(Paragraph("Executive Summary", heading_style))
        
        overall_risk = policy['risk_scores']['overall_risk']
        risk_level = "LOW" if overall_risk <= 30 else "MODERATE" if overall_risk <= 60 else "HIGH" if overall_risk <= 80 else "CRITICAL"
        
        summary_text = f"""
        This report provides a comprehensive analysis of the {policy['policy_type']} policy document.
        Overall Risk Score: {overall_risk}% - {risk_level} Risk
        Policy Validity: {policy.get('key_dates', {}).get('issue_date', 'Not specified')} to {policy.get('key_dates', {}).get('expiry_date', 'Not specified')}
        """
        story.append(Paragraph(summary_text, styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Policy Information
        story.append(Paragraph("Policy Information", heading_style))
        
        # Format sum insured for display
        sum_insured_display = policy['sum_insured']
        if policy['sum_insured'] != 'Not specified' and policy['sum_insured'].replace(',', '').replace('.', '').isdigit():
            try:
                sum_insured_display = f"₹{int(float(policy['sum_insured'].replace(',', ''))):,}"
            except:
                pass
        
        # Format premium for display
        premium_display = policy['premium']
        if policy['premium'] != 'Not specified' and policy['premium'].replace(',', '').replace('.', '').isdigit():
            try:
                premium_display = f"₹{int(float(policy['premium'].replace(',', ''))):,}"
            except:
                pass
        
        info_data = [
            ['Policy ID:', policy['id']],
            ['File:', policy['filename'][:50] + '...' if len(policy['filename']) > 50 else policy['filename']],
            ['Upload Date:', policy['upload_time']],
            ['Policy Type:', policy['policy_type']],
            ['Detected Type:', policy.get('detected_type', 'N/A')],
            ['Policy Number:', policy['policy_number']],
            ['Sum Insured:', sum_insured_display],
            ['Premium:', premium_display],
            ['Pages:', str(policy.get('page_count', 'N/A'))]
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#0a1e32')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # Risk Analysis
        story.append(Paragraph("Risk Analysis", heading_style))
        
        risk_scores = policy['risk_scores']
        
        # Risk scores table
        risk_data = [
            ['Risk Type', 'Score', 'Level'],
            ['Claim Coverage Risk', f"{risk_scores['coverage_risk']}%", 
             'High' if risk_scores['coverage_risk'] > 60 else 'Medium' if risk_scores['coverage_risk'] > 30 else 'Low'],
            ['Out-of-Pocket Risk', f"{risk_scores['cost_risk']}%",
             'High' if risk_scores['cost_risk'] > 60 else 'Medium' if risk_scores['cost_risk'] > 30 else 'Low'],
            ['Claim Delay Risk', f"{risk_scores['delay_risk']}%",
             'High' if risk_scores['delay_risk'] > 60 else 'Medium' if risk_scores['delay_risk'] > 30 else 'Low'],
            ['Overall Risk', f"{risk_scores['overall_risk']}%", risk_level]
        ]
        
        risk_table = Table(risk_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
        risk_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0a1e32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(risk_table)
        story.append(Spacer(1, 20))
        
        # Financial Details
        story.append(Paragraph("Financial Details", heading_style))
        
        financial = policy['financial_details']
        financial_data = [
            ['Co-pay Percentage:', f"{financial['co_pay_percentage']}%"],
            ['Deductible:', f"₹{financial['deductible']:,}" if financial['deductible'] > 0 else 'Not specified'],
            ['Room Rent Cap:', str(financial['room_rent_cap']) if financial['room_rent_cap'] else 'Not specified']
        ]
        
        if financial['sub_limits']:
            for limit_type, amount in financial['sub_limits'].items():
                financial_data.append([f"{limit_type.title()} Sub-limit:", f"₹{amount:,}"])
        
        financial_table = Table(financial_data, colWidths=[2.5*inch, 3.5*inch])
        financial_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#0a1e32')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(financial_table)
        story.append(Spacer(1, 20))
        
        # Key Benefits
        if policy.get('benefits'):
            story.append(Paragraph("Key Benefits", heading_style))
            for i, benefit in enumerate(policy['benefits'][:5], 1):
                story.append(Paragraph(f"{i}. {benefit['text']}", styles['Normal']))
                story.append(Spacer(1, 4))
            story.append(Spacer(1, 10))
        
        # Exclusions
        if policy['exclusions']:
            story.append(Paragraph("Important Exclusions", heading_style))
            for i, exclusion in enumerate(policy['exclusions'][:5], 1):
                story.append(Paragraph(f"{i}. {exclusion}", styles['Normal']))
                story.append(Spacer(1, 4))
            story.append(Spacer(1, 10))
        
        # Key Clauses
        if policy.get('clauses'):
            story.append(Paragraph("Key Policy Clauses", heading_style))
            for term, clause in list(policy['clauses'].items())[:5]:
                if clause != "Not mentioned in document":
                    story.append(Paragraph(f"<b>{term.title()}:</b> {clause[:150]}...", styles['Normal']))
                    story.append(Spacer(1, 4))
            story.append(Spacer(1, 10))
        
        # Recommendations
        story.append(Paragraph("Recommendations", heading_style))
        
        recommendations = []
        
        if overall_risk > 60:
            recommendations.append("• High risk policy - consider reviewing with an insurance advisor")
        if financial['co_pay_percentage'] > 20:
            recommendations.append(f"• High co-pay ({financial['co_pay_percentage']}%) will significantly reduce claim payouts")
        if financial['deductible'] > 50000:
            recommendations.append(f"• High deductible of ₹{financial['deductible']:,} requires substantial out-of-pocket payment")
        if policy['exclusions']:
            recommendations.append("• Review all exclusions carefully to understand coverage gaps")
        if policy.get('benefits'):
            recommendations.append(f"• Key benefits identified: {len(policy['benefits'])} areas of coverage")
        
        if not recommendations:
            recommendations.append("• No specific recommendations - policy appears standard")
        
        for rec in recommendations:
            story.append(Paragraph(rec, styles['Normal']))
            story.append(Spacer(1, 4))
        
        # Footer
        story.append(Spacer(1, 30))
        footer_text = f"Report generated by ClaimGuard on {datetime.now().strftime('%Y-%m-%d %H:%M')} | Confidential | ID: {policy['unique_id']}"
        story.append(Paragraph(footer_text, styles['Italic']))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'ClaimGuard_Report_{policy_id}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"PDF Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/recent-policies')
@login_required
def recent_policies():
    """Get recent analyzed policies for the current user"""
    try:
        policies = get_user_policies(session['user']['id'], limit=10)
        return jsonify(policies)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/policy/<policy_id>')
@login_required
def get_policy(policy_id):
    """Get specific policy details for the current user"""
    try:
        policy = get_policy_by_id(policy_id, session['user']['id'])
        if policy:
            return jsonify(policy)
        return jsonify({'error': 'Policy not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/policy-types')
@login_required
def get_policy_types():
    """Get available policy types"""
    try:
        return jsonify(list(PolicyAnalyzer.POLICY_TYPES.keys()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Cleanup old files (optional - can be run as a scheduled task)
@app.cli.command('cleanup')
def cleanup_old_files():
    """Clean up old uploaded files"""
    import shutil
    from pathlib import Path
    
    upload_dir = Path(app.config['UPLOAD_FOLDER'])
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
        upload_dir.mkdir()
        print(f"Cleaned up {upload_dir}")


if __name__ == '__main__':
    # Create necessary directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('static/images', exist_ok=True)
    os.makedirs('uploads', exist_ok=True)
    
    # Initialize database
    init_db_schema()
    
    app.run(debug=True, port=5000)