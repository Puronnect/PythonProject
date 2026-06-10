from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, Match, MatchOption, Bet, PointTransaction
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///worldcup.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('需要管理员权限')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

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

    if datetime.utcnow() >= match.lock_time:
        return jsonify({'success': False, 'message': '下注已截止'}), 400
    if amount < 1 or amount > 30:
        return jsonify({'success': False, 'message': '下注额度1-30积分'}), 400
    if current_user.points < amount:
        return jsonify({'success': False, 'message': '积分不足'}), 400

    # 扣积分
    current_user.points -= amount
    current_user.total_bet_amount += amount   # 统计总下注
    current_user.bet_count += 1

    bet = Bet(user_id=current_user.id, match_id=match.id, option_id=option_id, amount=amount)
    transaction = PointTransaction(
        user_id=current_user.id,
        amount=-amount,
        reason=f'下注 {match.title} - {option.option_name}'
    )

    db.session.add(bet)
    db.session.add(transaction)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'成功下注 {amount} 积分',
        'new_balance': current_user.points,
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
            login_user(user)
            return redirect(url_for('index'))
        else:
            user = User.query.filter_by(username=username).first()
            if user and user.password == password:
                login_user(user)
                return redirect(url_for('index'))
            flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ---------- 排行榜（盈利/胜率/下注次数） ----------
@app.route('/leaderboard')
def leaderboard():
    sort_by = request.args.get('sort', 'profit')  # profit / win_rate / bets
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
    bets = Bet.query.filter_by(user_id=current_user.id).order_by(Bet.bet_time.desc()).all()
    transactions = PointTransaction.query.filter_by(user_id=current_user.id).order_by(PointTransaction.time.desc()).limit(50).all()
    return render_template('profile.html', bets=bets, transactions=transactions)

# ---------- 管理后台 ----------
@app.route('/admin')
@login_required
@admin_required
def admin():
    matches = Match.query.order_by(Match.start_time.desc()).all()
    # 统计数据
    total_users = User.query.filter_by(is_admin=False).count()
    total_bets_amount = db.session.query(db.func.sum(Bet.amount)).scalar() or 0
    platform_fee = int(total_bets_amount * 0.05)   # 5% 手续费
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
        reason=f'管理员调整'   # 不带理由
    )
    db.session.add(transaction)
    db.session.commit()
    flash(f'已调整 {user.username} 积分 {amount:+d}')
    return redirect(url_for('admin_users'))

# 初始化管理员
def create_admin():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password='admin123', is_admin=True, points=999999)
            db.session.add(admin)
            db.session.commit()
            print('管理员账号：admin / admin123')

if __name__ == '__main__':
    create_admin()
    app.run(debug=True, host='0.0.0.0', port=5000)