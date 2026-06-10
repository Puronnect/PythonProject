from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    points = db.Column(db.Integer, default=0)
    is_admin = db.Column(db.Boolean, default=False)
    # 新增统计字段
    total_bet_amount = db.Column(db.Integer, default=0)   # 总下注积分
    total_win_amount = db.Column(db.Integer, default=0)   # 总中奖积分
    bet_count = db.Column(db.Integer, default=0)          # 下注次数
    win_count = db.Column(db.Integer, default=0)          # 猜中次数
    bets = db.relationship('Bet', backref='user', lazy=True)
    point_transactions = db.relationship('PointTransaction', backref='user', lazy=True)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    start_time = db.Column(db.DateTime, nullable=False)
    lock_time = db.Column(db.DateTime, nullable=False)
    is_settled = db.Column(db.Boolean, default=False)
    winning_option = db.Column(db.String(100))
    options = db.relationship('MatchOption', backref='match', lazy=True)

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
    reason = db.Column(db.String(200), nullable=True)  # 理由可为空
    time = db.Column(db.DateTime, default=datetime.utcnow)