"""
今天真棒 - Render.com 部署版本
使用 Flask + SQLite + Gunicorn
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import uuid
from datetime import datetime
import os
import threading

app = Flask(__name__)
CORS(app)

DATABASE = '/tmp/awesome.db'  # Render的临时目录

# 线程锁
lock = threading.Lock()

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            date TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            likes INTEGER DEFAULT 0,
            liked_users TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts(id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            date TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return jsonify({
        'status': 'ok',
        'message': '今天真棒，又活一天 💜',
        'version': '1.0'
    })

@app.route('/api/posts', methods=['GET'])
def get_posts():
    with lock:
        conn = get_db()
        c = conn.cursor()
        
        filter_type = request.args.get('filter', 'all')
        
        if filter_type == 'recent':
            three_days_ago = datetime.now().timestamp() * 1000 - 3 * 24 * 60 * 60 * 1000
            c.execute('SELECT * FROM posts ORDER BY timestamp DESC')
            posts = [dict(r) for r in c.fetchall() if r['timestamp'] > three_days_ago]
        elif filter_type == 'popular':
            c.execute('SELECT * FROM posts ORDER BY likes DESC')
            posts = [dict(r) for r in c.fetchall()]
        else:
            c.execute('SELECT * FROM posts ORDER BY timestamp DESC')
            posts = [dict(r) for r in c.fetchall()]
        
        conn.close()
        
        result = []
        for p in posts:
            c = conn.cursor() if conn else get_db()
            c.execute('SELECT * FROM comments WHERE post_id = ? ORDER BY created_at ASC', (p['id'],))
            comments = [dict(r) for r in c.fetchall()]
            c.close()
            
            result.append({
                'id': p['id'],
                'author': p['author'],
                'content': p['content'],
                'date': p['date'],
                'timestamp': p['timestamp'],
                'likes': p['likes'],
                'likedUsers': eval(p['liked_users']) if p['liked_users'] else [],
                'comments': comments
            })
        
        return jsonify(result)

@app.route('/api/posts', methods=['POST'])
def create_post():
    data = request.json
    
    if not data or not data.get('content'):
        return jsonify({'error': '内容不能为空'}), 400
    
    with lock:
        post_id = str(uuid.uuid4())
        now = datetime.now()
        
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO posts (id, author, content, date, timestamp, likes, liked_users, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            post_id,
            data.get('author', '匿名小伙伴'),
            data['content'],
            now.strftime('%Y年%m月%d日'),
            int(now.timestamp() * 1000),
            0,
            '[]',
            now.isoformat()
        ))
        
        today = now.strftime('%Y-%m-%d')
        c.execute('INSERT OR IGNORE INTO stats (date, count) VALUES (?, 0)', (today,))
        c.execute('UPDATE stats SET count = count + 1 WHERE date = ?', (today,))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'id': post_id,
            'author': data.get('author', '匿名小伙伴'),
            'content': data['content'],
            'date': now.strftime('%Y年%m月%d日'),
            'timestamp': int(now.timestamp() * 1000),
            'likes': 0,
            'likedUsers': [],
            'comments': []
        })

@app.route('/api/posts/<post_id>/like', methods=['POST'])
def like_post(post_id):
    data = request.json
    user_id = data.get('userId', '')
    
    with lock:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = c.fetchone()
        
        if not post:
            conn.close()
            return jsonify({'error': '帖子不存在'}), 404
        
        liked_users = eval(post['liked_users']) if post['liked_users'] else []
        
        if user_id in liked_users:
            liked_users.remove(user_id)
            new_likes = post['likes'] - 1
        else:
            liked_users.append(user_id)
            new_likes = post['likes'] + 1
        
        c.execute('UPDATE posts SET likes = ?, liked_users = ? WHERE id = ?', 
                  (new_likes, str(liked_users), post_id))
        conn.commit()
        conn.close()
        
        return jsonify({'likes': new_likes, 'likedUsers': liked_users})

@app.route('/api/posts/<post_id>/comments', methods=['POST'])
def add_comment(post_id):
    data = request.json
    
    if not data or not data.get('content'):
        return jsonify({'error': '评论内容不能为空'}), 400
    
    with lock:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('SELECT id FROM posts WHERE id = ?', (post_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': '帖子不存在'}), 404
        
        comment_id = str(uuid.uuid4())
        now = datetime.now()
        
        c.execute('''
            INSERT INTO comments (id, post_id, author, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (comment_id, post_id, data.get('author', '陌生人'), data['content'], now.isoformat()))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'id': comment_id,
            'postId': post_id,
            'author': data.get('author', '陌生人'),
            'content': data['content'],
            'createdAt': now.isoformat()
        })

@app.route('/api/stats', methods=['GET'])
def get_stats():
    with lock:
        conn = get_db()
        c = conn.cursor()
        
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute('SELECT count FROM stats WHERE date = ?', (today,))
        row = c.fetchone()
        today_count = row['count'] if row else 0
        
        c.execute('SELECT COUNT(*) as count FROM posts')
        total_posts = c.fetchone()['count']
        
        conn.close()
        
        return jsonify({'todayCount': today_count, 'totalPosts': total_posts})

# Render 需要的
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
