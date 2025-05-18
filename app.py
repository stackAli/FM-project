import random
from flask import Flask, render_template, request, redirect, session, url_for ,flash
import pyodbc




app = Flask(__name__)
app.secret_key = 'your_secret_keyabcd'


# DB connection
# DB connection using a context manager
def get_db_connection():
    return pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};'
                          'SERVER=DESKTOP-KKL51JC\\SQLEXPRESS;'
                          'DATABASE=Fraudbusters;'
                          'Trusted_Connection=yes;')


@app.route('/')
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT PlayerName FROM Players")
    players = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template('index.html', players=players)








# Fetch all investments from the database

# Fetch all market events from the database
def get_market_events(cursor):
    cursor.execute("SELECT EventID, Name, EffectDescription, EffectValue FROM MarketEvents")
    return cursor.fetchall()

# Fetch all financing options from the database
def get_financing_options(cursor):
    cursor.execute("SELECT FinancingID, Name, Modifier FROM FinancingOptions")
    return cursor.fetchall()
def row_to_dict(row):
        return {col[0]: getattr(row, col[0]) for col in row.cursor_description} if row else None

# Simulate rolling a dice for endgame twist
def roll_dice():
    return random.randint(1, 6)

def calculate_npv(cashflow, years_remaining, discount_rate=0.10):
    """
    Calculates NPV of a constant cashflow over years_remaining with given discount rate.
    NPV = Cashflow * (1 - (1 + r)^-n ) / r
    """
    if years_remaining == 0:
        return 0
    npv = cashflow * (1 - (1 + discount_rate) ** (-years_remaining)) / discount_rate
    return npv

def calculate_total_npv(cash_flow_per_year, years=5, discount_rate=0.1):
    total_npv = 0
    for year in range(1, years + 1):
        total_npv += calculate_npv(cash_flow_per_year, year, discount_rate)
    return total_npv

@app.route('/start_game', methods=['GET', 'POST'])
def start_game():
    if request.method == 'POST':
        player_names = [request.form.get(f'player{i}') for i in range(1, 4)]
        session['players'] = {
            name: {"capital": 100000, "npv": 0.0, "fraud_detection_cards": 1, "rounds_played": 0}
            for name in player_names if name
        }
        session['round'] = 1
        session['current_player_index'] = 0
        return redirect(url_for('play_round'))
    return render_template('start_game.html')
@app.route('/play_round', methods=['GET', 'POST'])
def play_round():
    players = session.get('players')
    if not players:
        return redirect(url_for('home'))

    current_index = session.get('current_player_index', 0)
    player_names = list(players.keys())
    current_player = player_names[current_index]
    player_data = players[current_player]
    round_num = player_data['rounds_played'] + 1
    years_remaining = max(0, 6 - round_num)

    if player_data['rounds_played'] >= 5:
        session['current_player_index'] = (current_index + 1) % len(players)
        return redirect(url_for('play_round'))

    if round_num == 1:
        session.pop('investments', None)
        session.pop('fraud_checked', None)
        session.pop('npv_penalty', None)
        session.pop('fraud_redraw_used', None)
        session.pop('auto_choice', None)

    if 'investments' not in session:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                f"FROM Investments {'WHERE Amount <= 100000' if round_num == 1 else ''} ORDER BY NEWID()"
            )
            all_investments = [row_to_dict(row) for row in cursor.fetchall()]

            unique_investments = []
            seen_ids = set()
            for inv in all_investments:
                if inv['InvestmentID'] not in seen_ids:
                    unique_investments.append(inv)
                    seen_ids.add(inv['InvestmentID'])
                if len(unique_investments) == 2:
                    break

            if len(unique_investments) < 2:
                flash("Not enough distinct investment options available!", "danger")
                return redirect(url_for('home'))

            session['investments'] = unique_investments
        session['fraud_checked'] = False
        session['npv_penalty'] = False
        session['fraud_redraw_used'] = False
        session['auto_choice'] = None

    investment_1, investment_2 = session['investments']

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT TOP 1 * FROM MarketEvents ORDER BY NEWID()")
        market_event = row_to_dict(cursor.fetchone()) or {}

        financing_options = []
        if round_num >= 2:
            cursor.execute("SELECT * FROM FinancingOptions")
            financing_options = [row_to_dict(row) for row in cursor.fetchall()]

    if player_data['capital'] <= 0 and not financing_options:
        flash(f"{current_player} has no capital left and no financing options. Skipping turn.", "danger")
        player_data['rounds_played'] += 1
        session['current_player_index'] = (current_index + 1) % len(players)
        return redirect(url_for('play_round'))

    if request.method == 'POST':
        use_fraud_card = request.form.get('fraud_card') == 'yes'
        choice = request.form.get('choice')
        financing_choice = request.form.get('financing_choice')

        fraud_1 = investment_1['IsFraudulent']
        fraud_2 = investment_2['IsFraudulent']

        # Fraud card logic (can be reused until misused)
        if use_fraud_card and not session.get('fraud_checked'):
            session['fraud_checked'] = True

            # Redraw both if both are fraudulent
            if fraud_1 and fraud_2 and not session.get('fraud_redraw_used'):
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                        f"FROM Investments {'WHERE Amount <= 100000' if round_num == 1 else ''} ORDER BY NEWID()"
                    )
                    all_investments = [row_to_dict(row) for row in cursor.fetchall()]
                    unique_investments = []
                    seen_ids = set()
                    for inv in all_investments:
                        if inv['InvestmentID'] not in seen_ids:
                            unique_investments.append(inv)
                            seen_ids.add(inv['InvestmentID'])
                        if len(unique_investments) == 2:
                            break

                    if len(unique_investments) < 2:
                        flash("Not enough distinct investments for fraud redraw!", "danger")
                        return redirect(url_for('home'))

                    session['investments'] = unique_investments
                session['fraud_redraw_used'] = True
                flash("Both investments were fraudulent! Redrawn. You keep your turn.", "warning")
                return redirect(url_for('play_round'))

            if fraud_1 and not fraud_2:
                flash(f"Fraud detected! '{investment_1['Name']}' is fraudulent. Auto-selecting '{investment_2['Name']}'.", "success")
                session['auto_choice'] = '2'
            elif fraud_2 and not fraud_1:
                flash(f"Fraud detected! '{investment_2['Name']}' is fraudulent. Auto-selecting '{investment_1['Name']}'.", "success")
                session['auto_choice'] = '1'
            elif not fraud_1 and not fraud_2:
                flash("Both projects are legit. Misuse of fraud card! Your card is now revoked.", "danger")
                session['npv_penalty'] = True
                player_data['fraud_detection_cards'] = 0  # Revoke card permanently

        if choice or session.get('auto_choice'):
            selected = session.pop('auto_choice', None) or choice
            selected_investment = investment_1 if selected == '1' else investment_2

            investment_amount = selected_investment['Amount']
            investment_cashflow = selected_investment['CashFlow']
            is_fraudulent = selected_investment['IsFraudulent']

            total_discounted_cash_flow = sum(
                calculate_npv(investment_cashflow, year) for year in range(1, years_remaining + 1)
            )
            npv = total_discounted_cash_flow - investment_amount
            npv += market_event.get('EffectValue', 0)

            if is_fraudulent:
                npv -= 100

            if session.get('npv_penalty'):
                npv *= 0.5
                session['npv_penalty'] = False

            modifier = 0
            selected_option = None
            if financing_choice:
                selected_option = next((f for f in financing_options if str(f['FinancingID']) == financing_choice), None)
                if selected_option:
                    modifier = selected_option['Modifier']
                    npv += modifier

            starting_capital = player_data['capital']
            capital_shortfall = investment_amount - starting_capital

            if capital_shortfall <= 0:
                player_data['capital'] -= investment_amount
            else:
                if not financing_choice:
                    flash("Insufficient capital! Please choose a financing option.", "danger")
                    return redirect(url_for('play_round'))
                player_data['capital'] -= min(investment_amount, player_data['capital'])

            player_data['capital'] = max(player_data['capital'], 0)
            round_npv = round(npv, 2)
            player_data['npv'] += round_npv
            player_data['rounds_played'] += 1
            ending_capital = player_data['capital']

            # Save round NPV for display
            player_data['last_round_npv'] = round_npv

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO GameDashboard (
                        PlayerName, RoundNumber, StartingCapital, InvestmentChosen,
                        InitialInvestment, FinancingMethod, MarketEvent,
                        EndingCapital, NPV, FraudDetected, FinalOutcome
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    current_player,
                    round_num,
                    starting_capital,
                    selected_investment['Name'],
                    investment_amount,
                    selected_option['Name'] if selected_option else None,
                    market_event.get('Name'),
                    ending_capital,
                    round_npv,
                    is_fraudulent,
                    None
                ))
                conn.commit()

            session.pop('investments', None)
            session.pop('fraud_checked', None)
            session.pop('fraud_redraw_used', None)
            session.pop('auto_choice', None)

            if all(p['rounds_played'] >= 5 for p in players.values()):
                return redirect(url_for('endgame'))

            session['current_player_index'] = (current_index + 1) % len(players)
            return redirect(url_for('play_round'))

    return render_template(
        'play_round.html',
        round=round_num,
        player=current_player,
        investment_1=investment_1,
        investment_2=investment_2,
        financing_options=financing_options,
        market_event=market_event,
        player_capital=player_data['capital'],
        player_cumulative_npv=round(player_data['npv'], 2),
        player_round_npv=player_data.get('last_round_npv', None),
        player_fraud_detection_cards=player_data['fraud_detection_cards'],
        fraud_checked=session.get('fraud_checked', False),
    )

@app.route('/endgame')
def endgame():
    print("ENDGAME route hit!")
    players = session.get('players')
    if not players:
        return redirect(url_for('home'))

    print("DEBUG players:", players)  # Add this to check players content

    events = {}
    dice_rolls = {}

    for player_id, player in players.items():
        dice_roll = roll_dice()
        event = None

        if dice_roll <= 2:
            event = "Hostile Takeover"
            player['npv'] *= 0.8
        elif dice_roll == 4:
            event = "IPO Opportunity"
            player['npv'] *= 1.3
        else:
            event = "No Event"

        dice_rolls[player_id] = dice_roll
        events[player_id] = event

    session['players'] = players
    session['dice_rolls'] = dice_rolls
    session['events'] = events

    return render_template('endgame.html', players=players, dice_rolls=dice_rolls, events=events)

@app.route('/final_results')
def final_results():
    players = session.get('players')
    if not players:
        return redirect(url_for('home'))  # If there are no players, redirect to the home page

    # Create a copy with NPV rounded to 2 decimal places
    players_rounded = {
        name: {
            **data,
            'npv': round(data.get('npv', 0), 2)
        } for name, data in players.items()
    }

    winner = max(players_rounded.items(), key=lambda item: item[1]['npv'])[0]
    event = session.get('event')  # Retrieve event that occurred during endgame
    dice_roll = session.get('dice_roll')  # Retrieve the dice roll from session

    return render_template('final_results.html', players=players_rounded, winner=winner, event=event, dice_roll=dice_roll)

@app.route('/scoreboard')
def scoreboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get last 3 players by latest play time
    cursor.execute("""
        SELECT TOP 3 PlayerName
        FROM GameDashboard
        GROUP BY PlayerName
        ORDER BY MAX(Timestamp) DESC
    """)
    recent_players = [row.PlayerName for row in cursor.fetchall()]

    if not recent_players:
        cursor.close()
        conn.close()
        return render_template('scoreboard.html', scoreboard=[])

    query = """
        SELECT 
            PlayerName,
            RoundNumber,
            NPV,
            EndingCapital,
            FraudDetected,
            Timestamp
        FROM GameDashboard
        WHERE PlayerName IN ({})
        ORDER BY PlayerName, RoundNumber
    """.format(','.join('?' * len(recent_players)))

    cursor.execute(query, recent_players)
    rows = cursor.fetchall()

    scoreboard_data = {}
    for row in rows:
        pname = row.PlayerName
        if pname not in scoreboard_data:
            scoreboard_data[pname] = {
                'name': pname,
                'rounds_played': 0,
                'total_npv': 0.0,
                'current_capital': 0.0,
                'frauds_detected': 0,
                'fraud_detection_cards': 0,
                'rounds': []
            }
        scoreboard_data[pname]['rounds_played'] += 1
        scoreboard_data[pname]['total_npv'] += row.NPV or 0
        scoreboard_data[pname]['current_capital'] = row.EndingCapital or scoreboard_data[pname]['current_capital']
        scoreboard_data[pname]['rounds'].append({
            'round_number': row.RoundNumber,
            'npv': row.NPV,
            'capital': row.EndingCapital,
            'fraud_detected': row.FraudDetected or 0,
            'timestamp': row.Timestamp.strftime('%Y-%m-%d %H:%M:%S') if row.Timestamp else 'N/A'
        })

    cursor.close()
    conn.close()

    return render_template('scoreboard.html', scoreboard=list(scoreboard_data.values()))

if __name__ == '__main__':
    app.run(debug=True)
