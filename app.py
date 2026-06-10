import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from functools import wraps
from models import db, User, Match, MatchOption, Bet, PointTransaction
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-very-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/worldcup.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# ---------- 自定义登录工具（替代 flask-login） ----------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('需要管理员权限')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# 注入 current_user 到所有模板
@app.context_processor
def inject_user():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        return dict(current_user=user)
    return dict(current_user=None)

# ---------- 首页 ----------
@app.route('/')
def index():
    now = datetime.utcnow()
    matches = Match.query.order_by(Match.start_time.desc()).all()
    upcoming = [m for m in matches if m.start_time > now and not m.is_settled]
    ongoing = [m for m in matches if m.start_time <= now and not m.is_settled]
    settled = [m for m in matches if m.is_settled]
    return render_template('index.html',
                           upcoming=upcoming, ongoing=ongoing, settled=settled, now=now)

# ---------- 比赛详情 ----------
@app.route('/match/<int:match_id>')
def match_detail(match_id):
    match = Match.query.get_or_404(match_id)
    now = datetime.utcnow()
    can_bet = now < match.lock_time and not match.is_settled
    return render_template('match.html', match=match, can_bet=can_bet, now=now)

# ---------- 下注 API ----------
@app.route('/api/bet', methods=['POST'])
@login_required
def place_bet():
    data = request.json
    option_id = data.get('option_id')
    amount = data.get('amount')

    option = MatchOption.query.get_or_404(option_id)
    match = option.match
    user = User.query.get(session['user_id'])

    if datetime.utcnow() >= match.lock_time:
        return jsonify({'success': False, 'message': '下注已截止'}), 400
    if amount < 1 or amount > 30:
        return jsonify({'success': False, 'message': '下注额度1-30积分'}), 400
    if user.points < amount:
        return jsonify({'success': False, 'message': '积分不足'}), 400

    user.points -= amount
    user.total_bet_amount += amount
    user.bet_count += 1

    bet = Bet(user_id=user.id, match_id=match.id, option_id=option_id, amount=amount)
    transaction = PointTransaction(
        user_id=user.id,
        amount=-amount,
        reason=f'下注 {match.title} - {option.option_name}'
    )

    db.session.add(bet)
    db.session.add(transaction)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'成功下注 {amount} 积分',
        'new_balance': user.points,
        'new_odds': option.odds
    })

# ---------- 实时赔率 ----------
@app.route('/api/odds/<int:match_id>')
def get_odds(match_id):
    match = Match.query.get_or_404(match_id)
    odds_data = {}
    for option in match.options:
        odds_data[option.id] = {
            'name': option.option_name,
            'odds': option.odds,
            'total_bet': option.total_bet_amount
        }
    return jsonify(odds_data)

# ---------- 结算比赛 ----------
@app.route('/api/settle/<int:match_id>', methods=['POST'])
@login_required
@admin_required
def settle_match(match_id):
    match = Match.query.get_or_404(match_id)
    data = request.json
    winning_option_id = int(data.get('winning_option_id'))

    if match.is_settled:
        return jsonify({'success': False, 'message': '比赛已结算'}), 400

    winning_option = MatchOption.query.get(winning_option_id)
    for bet in match.bets:
        user = User.query.get(bet.user_id)
        if bet.option_id == winning_option_id:
            win_amount = int(bet.amount * winning_option.odds)
            bet.win_amount = win_amount
            user.points += win_amount
            user.total_win_amount += win_amount
            user.win_count += 1
            transaction = PointTransaction(
                user_id=user.id,
                amount=win_amount,
                reason=f'猜中 {match.title} - {winning_option.option_name}'
            )
            db.session.add(transaction)
        bet.is_settled = True

    match.is_settled = True
    match.winning_option = str(winning_option_id)
    db.session.commit()

    return jsonify({'success': True, 'message': '结算完成'})

# ---------- 登录/注册 ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        action = request.form.get('action')

        if action == 'register':
            confirm = request.form.get('confirm_password')
            if password != confirm:
                flash('两次密码不一致')
                return redirect(url_for('login'))
            if User.query.filter_by(username=username).first():
                flash('用户名已存在')
                return redirect(url_for('login'))
            user = User(username=username, password=password)
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id   # 注册后自动登录
            return redirect(url_for('index'))
        else:   # 登录
            user = User.query.filter_by(username=username).first()
            if user and user.password == password:
                session['user_id'] = user.id
                return redirect(url_for('index'))
            flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

# ---------- 排行榜 ----------
@app.route('/leaderboard')
def leaderboard():
    sort_by = request.args.get('sort', 'profit')
    users = User.query.filter_by(is_admin=False).all()
    if sort_by == 'profit':
        users.sort(key=lambda u: (u.total_win_amount - u.total_bet_amount), reverse=True)
    elif sort_by == 'win_rate':
        users.sort(key=lambda u: (u.win_count / u.bet_count) if u.bet_count > 0 else 0, reverse=True)
    elif sort_by == 'bets':
        users.sort(key=lambda u: u.bet_count, reverse=True)
    return render_template('leaderboard.html', users=users, sort_by=sort_by)

# ---------- 个人中心 ----------
@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    bets = Bet.query.filter_by(user_id=user.id).order_by(Bet.bet_time.desc()).all()
    transactions = PointTransaction.query.filter_by(user_id=user.id).order_by(PointTransaction.time.desc()).limit(50).all()
    return render_template('profile.html', bets=bets, transactions=transactions)

# ---------- 管理后台 ----------
@app.route('/admin')
@login_required
@admin_required
def admin():
    matches = Match.query.order_by(Match.start_time.desc()).all()
    total_users = User.query.filter_by(is_admin=False).count()
    total_bets_amount = db.session.query(db.func.sum(Bet.amount)).scalar() or 0
    platform_fee = int(total_bets_amount * 0.05)
    return render_template('admin.html',
                           matches=matches,
                           total_users=total_users,
                           total_bets_amount=total_bets_amount,
                           platform_fee=platform_fee)

@app.route('/admin/create_match', methods=['POST'])
@login_required
@admin_required
def create_match():
    title = request.form.get('title')
    description = request.form.get('description')
    start_time = datetime.strptime(request.form.get('start_time'), '%Y-%m-%dT%H:%M')
    lock_time = datetime.strptime(request.form.get('lock_time'), '%Y-%m-%dT%H:%M')
    options = request.form.getlist('options[]')

    match = Match(title=title, description=description, start_time=start_time, lock_time=lock_time)
    db.session.add(match)
    for option_name in options:
        if option_name.strip():
            option = MatchOption(match=match, option_name=option_name.strip())
            db.session.add(option)
    db.session.commit()
    flash('比赛创建成功')
    return redirect(url_for('admin'))

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.filter_by(is_admin=False).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/adjust_points', methods=['POST'])
@login_required
@admin_required
def adjust_points():
    user_id = request.form.get('user_id')
    amount = int(request.form.get('amount'))
    user = User.query.get_or_404(user_id)
    user.points += amount
    transaction = PointTransaction(
        user_id=user_id,
        amount=amount,
        reason='管理员调整'
    )
    db.session.add(transaction)
    db.session.commit()
    flash(f'已调整 {user.username} 积分 {amount:+d}')
    return redirect(url_for('admin_users'))

# ---------- 初始化数据库和默认管理员 ----------
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin', password='admin123', is_admin=True, points=999999)
        db.session.add(admin_user)
        db.session.commit()
        print('默认管理员已创建：admin / admin123')

# ---------- 管理员下载数据库备份 ----------
@app.route('/admin/download_backup')
@login_required
@admin_required
def download_backup():
    db_path = '/tmp/worldcup.db'
    if not os.path.exists(db_path):
        flash('数据库文件不存在')
        return redirect(url_for('admin'))
    from flask import send_file
    return send_file(db_path, as_attachment=True, download_name='worldcup_backup.db')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))