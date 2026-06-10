from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    points = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)
    total_bet_amount = db.Column(db.Integer, default=0)
    total_win_amount = db.Column(db.Integer, default=0)
    bet_count = db.Column(db.Integer, default=0)
    win_count = db.Column(db.Integer, default=0)
    bets = db.relationship('Bet', backref='user', lazy=True)
    point_transactions = db.relationship('PointTransaction', backref='user', lazy=True)

    # 以下属性模拟 flask_login 的 UserMixin，让模板中的 current_user 正常工作
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime, nullable=False)
    lock_time = db.Column(db.DateTime, nullable=False)
    is_settled = db.Column(db.Boolean, default=False)
    winning_option = db.Column(db.String(100))
    options = db.relationship('MatchOption', backref='match', lazy=True)
    bets = db.relationship('Bet', backref='match', lazy=True)   # ← 添加这一行

class MatchOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    option_name = db.Column(db.String(100), nullable=False)
    bets = db.relationship('Bet', backref='option', lazy=True)

    @property
    def total_bet_amount(self):
        return sum(bet.amount for bet in self.bets)

    @property
    def odds(self):
        match = self.match
        all_options = match.options
        total_pool = sum(opt.total_bet_amount for opt in all_options)
        if total_pool == 0 or self.total_bet_amount == 0:
            return 1.0
        prize_pool = total_pool * 0.95
        return round(prize_pool / self.total_bet_amount, 2)

class Bet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('match_option.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    bet_time = db.Column(db.DateTime, default=datetime.utcnow)
    is_settled = db.Column(db.Boolean, default=False)
    win_amount = db.Column(db.Integer, default=0)

class PointTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    time = db.Column(db.DateTime, default=datetime.utcnow)