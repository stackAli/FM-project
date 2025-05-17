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
    years_remaining = max(0, 6 - round_num)  # dynamic discounting

    # If player finished 5 rounds, switch to next player automatically
    if player_data['rounds_played'] >= 5:
        session['current_player_index'] = (current_index + 1) % len(players)
        return redirect(url_for('play_round'))

    # Clear old investments and fraud session flags at the start of first round
    if round_num == 1:
        session.pop('investments', None)
        session.pop('fraud_checked', None)
        session.pop('npv_penalty', None)
        session.pop('fraud_redraw_used', None)
        session.pop('auto_choice', None)

    # Load new investments if not already in session
    if 'investments' not in session:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if round_num == 1:
                cursor.execute(
                    "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                    "FROM Investments WHERE Amount <= 100000 ORDER BY NEWID()"
                )
            else:
                cursor.execute(
                    "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                    "FROM Investments ORDER BY NEWID()"
                )
            all_investments = [row_to_dict(row) for row in cursor.fetchall()]

            # Ensure 2 unique investments
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
        # Reset fraud related session flags
        session['fraud_checked'] = False
        session['npv_penalty'] = False
        session['fraud_redraw_used'] = False
        session['auto_choice'] = None

    investment_1, investment_2 = session['investments']

    # Load a random market event and financing options (if round >= 2)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT TOP 1 * FROM MarketEvents ORDER BY NEWID()")
        market_event = row_to_dict(cursor.fetchone()) or {}

        financing_options = []
        if round_num >= 2:
            cursor.execute("SELECT * FROM FinancingOptions")
            financing_options = [row_to_dict(row) for row in cursor.fetchall()]

    # Guard: skip turn if no capital and no financing options
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

        # Fraud card usage logic
        if use_fraud_card and player_data['fraud_detection_cards'] > 0 and not session.get('fraud_checked'):
            session['fraud_checked'] = True
            player_data['fraud_detection_cards'] -= 1

            # Both investments fraudulent? Redraw once per round
            if fraud_1 and fraud_2 and not session.get('fraud_redraw_used'):
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    if round_num == 1:
                        cursor.execute(
                            "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                            "FROM Investments WHERE Amount <= 100000 ORDER BY NEWID()"
                        )
                    else:
                        cursor.execute(
                            "SELECT InvestmentID, Name, Amount, CashFlow, RiskLevel, FraudHint, IsFraudulent "
                            "FROM Investments ORDER BY NEWID()"
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

            # One investment fraudulent? Auto-select the other
            if fraud_1 and not fraud_2:
                flash(f"Fraud detected! '{investment_1['Name']}' is fraudulent. Auto-selecting '{investment_2['Name']}'.", "success")
                session['auto_choice'] = '2'
            elif fraud_2 and not fraud_1:
                flash(f"Fraud detected! '{investment_2['Name']}' is fraudulent. Auto-selecting '{investment_1['Name']}'.", "success")
                session['auto_choice'] = '1'
            elif not fraud_1 and not fraud_2:
                flash("Both projects are legit. Misuse of fraud card! 50% NPV penalty applied.", "danger")
                session['npv_penalty'] = True

        # Handle investment selection (manual or auto)
        if choice or session.get('auto_choice'):
            selected = session.pop('auto_choice', None) or choice
            selected_investment = investment_1 if selected == '1' else investment_2

            investment_amount = selected_investment['Amount']
            investment_cashflow = selected_investment['CashFlow']
            is_fraudulent = selected_investment['IsFraudulent']

            # Calculate discounted cash flow and NPV
            total_discounted_cash_flow = sum(
                calculate_npv(investment_cashflow, year) for year in range(1, years_remaining + 1)
            )
            npv = total_discounted_cash_flow - investment_amount
            npv += market_event.get('EffectValue', 0)

            if is_fraudulent:
                npv -= 100  # Penalty for fraudulent investment

            if session.get('npv_penalty'):
                npv *= 0.5  # 50% penalty
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
                # Enough capital to pay full amount
                player_data['capital'] -= investment_amount
            else:
                # Not enough capital, financing choice required
                if not financing_choice:
                    flash("Insufficient capital! Please choose a financing option to cover the shortfall.", "danger")
                    return redirect(url_for('play_round'))
                # Pay what capital you have, financing covers the rest
                player_data['capital'] -= min(investment_amount, player_data['capital'])

            player_data['capital'] = max(player_data['capital'], 0)
            player_data['npv'] += round(npv, 2)
            player_data['rounds_played'] += 1
            ending_capital = player_data['capital']

            # Insert round data into GameDashboard table
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
                    round(npv, 2),
                    is_fraudulent,
                    None
                ))
                conn.commit()

            # Clear session investment and fraud flags for next round
            session.pop('investments', None)
            session.pop('fraud_checked', None)
            session.pop('fraud_redraw_used', None)
            session.pop('auto_choice', None)

            # Check if all players completed 5 rounds
            if all(p['rounds_played'] >= 5 for p in players.values()):
                return redirect(url_for('endgame'))

            # Move to next player
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
        player_npv=round(player_data['npv'], 2),
        player_fraud_detection_cards=player_data['fraud_detection_cards'],
        fraud_checked=session.get('fraud_checked', False),
    )

@app.route('/endgame')
def endgame():
    players = session.get('players')
    if not players:
        return redirect(url_for('home'))  

    dice_roll = roll_dice()  
    event = None

   
    if dice_roll <= 2:
        event = "Hostile Takeover"
        for player in players.values():
            player['npv'] *= 0.8  # Reduce all players' NPV by 20% in case of hostile takeover
    elif dice_roll == 4:
        event = "IPO Opportunity"
        for player in players.values():
            player['npv'] *= 1.3  # Increase all players' NPV by 30% in case of IPO opportunity

    # Update the session with the new player data and event
    session['players'] = players
    session['event'] = event
    session['dice_roll'] = dice_roll  # Store the dice roll result in the session for debugging/logging

    # Check if the event was properly assigned and stored
    print(f"Dice Roll: {dice_roll}, Event: {event}")  # For debugging purposes

    # Return the endgame page before redirecting to final results
    return render_template('endgame.html', dice_roll=dice_roll, event=event)  # Render endgame page first

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



if __name__ == '__main__':
    app.run(debug=True)
