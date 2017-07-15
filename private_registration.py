import csv
import io
import logging
import re
import sys
import time

from flask import (
    current_app as app, jsonify, redirect, render_template,
    render_template_string, request, send_file, session, url_for
)
from hashlib import md5
from os import path, urandom

from CTFd.models import db, Teams
from CTFd.utils import admins_only, cache, override_template

from CTFd import utils


class InvitedTeams(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True)
    email = db.Column(db.String(128), unique=True)
    token = db.Column(db.String(32), unique=True)

    def __init__(self, name, email, token):
        self.name = name
        self.email = email
        self.token = token


def add_to_invitation_list(csv_file):
    team_list = csv_file.read().splitlines()
    team_list = list(csv.reader(team_list))
    messages = []
    errors = []

    line_no = 0
    number_of_invited_teams = 0

    for team in team_list:
        line_no += 1

        if len(team) != 2:
            if len(team) != 0:
                errors.append('Invalid number of fields on line %d' % line_no)
            continue

        name = team[0]
        email = team[1]

        name_len = len(name) == 0
        valid_email = re.match(
            r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", email)
        registered_names = Teams.query.add_columns('name').filter_by(
            name=name).first()
        registered_emails = Teams.query.add_columns('email').filter_by(
            email=email).first()
        invited_names = InvitedTeams.query.add_columns('name').filter_by(
            name=name).first()
        invited_emails = InvitedTeams.query.add_columns('email').filter_by(
            email=email).first()

        # To check if there are any additional errors later
        errors_len = len(errors)

        if name_len:
            errors.append('Invalid team name on line %d' % line_no)
        if not valid_email:
            errors.append('Invalid email on line %d' % line_no)
        if registered_names:
            errors.append('Already registered team name on line %d' % line_no)
        if registered_emails:
            errors.append('Already registered email on line %d' % line_no)
        if invited_names:
            errors.append('Already invited team name on line %d' % line_no)
        if invited_emails:
            errors.append('Already invited email on line %d' % line_no)

        if len(errors) == errors_len:  # No additional errors at this point
            token = md5(urandom(64)).hexdigest()
            invited_team = InvitedTeams(name, email, token)
            db.session.add(invited_team)
            number_of_invited_teams += 1

    db.session.commit()
    db.session.close()

    if number_of_invited_teams > 0:
        messages.append('Succesfully added %d teams to invitation list'
                        % number_of_invited_teams)

    return messages, errors


def get_invited_teams_csv():
    # Hack to support in-memory IO stream both in Python 2 & Python 3
    if sys.version_info[0] >= 3:
        output = io.StringIO()
    else:
        output = io.BytesIO()

    writer = csv.writer(output)
    invited_teams = InvitedTeams.query.order_by(InvitedTeams.id.asc()).all()
    writer.writerow(['team_name', 'team_email', 'token'])

    for team in invited_teams:
        writer.writerow([team.name, team.email, team.token])

    if sys.version_info[0] >= 3:  # We need to convert IO to BytesIO in Python 3
        bytes_output = io.BytesIO()
        bytes_output.write(output.getvalue().encode('utf-8'))
        output = bytes_output

    output.seek(0)
    return output


def override_register_template():
    dir_path = path.dirname(path.realpath(__file__))
    template_path = None
    selected_option = utils.get_config('private_registration_option')

    if selected_option == 'token':
        template_path = '/templates/private-registration-token.html'
    elif selected_option == 'email':
        template_path = '/templates/private-registration-email.html'

    if template_path:
        template_path = dir_path + template_path
        with open(template_path, 'r') as register_template:
            override_template('register.html', register_template.read())


def load(app):
    app.db.create_all()

    @app.route('/admin/invited_teams/', methods=['GET'])
    @admins_only
    def get_invited_teams():
        teams = Teams.query.add_columns('name').all()

        registered_teams = {}
        for team in teams:
            registered_teams[team.name] = True

        invited_teams = InvitedTeams.query.order_by(InvitedTeams.id.asc()).all()

        json = {'invited_teams': []}
        for team in invited_teams:
            if team.name in registered_teams:
                registered = True
            else:
                registered = False
            json['invited_teams'].append(
                {'id': team.id, 'name': team.name, 'email': team.email,
                 'token': team.token, 'registered': registered})

        return jsonify(json)


    @app.route('/admin/invited_teams/delete/<int:id>', methods=['POST'])
    @admins_only
    def delete_invited_team(id):
        try:
            InvitedTeams.query.filter_by(id=id).delete()
            db.session.commit()
            db.session.close()
        except DatabaseError:
            return '0'
        else:
            return '1'


    @app.route('/admin/invited_teams/delete/all', methods=['POST'])
    @admins_only
    def remove_all_invited_teams():
        try:
            InvitedTeams.query.delete()
            db.session.commit()
            db.session.close()
        except DatabaseError:
            return '0'
        else:
            return '1'


    @app.route('/admin/invited_teams/export', methods=['GET'])
    @admins_only
    def export_csv():
        output = get_invited_teams_csv()
        ctf_name = utils.ctf_name()
        full_name = '{}-invited-teams.csv'.format(ctf_name)
        return send_file(output, as_attachment=True,
                         attachment_filename=full_name)


    @app.route('/admin/invited_teams/import', methods=['POST'])
    @admins_only
    def import_csv():
        if 'invited_teams' in request.files:
            csv_file = request.files['invited_teams']
            messages, errors = add_to_invitation_list(csv_file)
            json = {'messages': messages, 'errors': errors}
            return jsonify(json)
        else:
            return '0'


    @app.route('/admin/invited_teams/option', methods=['POST'])
    @admins_only
    def set_option():
        with app.app_context():
            cache.clear()
        selected_option = request.form.get('selected_option', None)
        if selected_option:
            utils.set_config('private_registration_option', selected_option)
            override_register_template()
            return '1'
        else:
            return '0'


    @app.route('/admin/invited_teams/send_invitation', methods=['POST'])
    @admins_only
    def send_invitation_all():
        if utils.can_send_mail():
            selected_option = utils.get_config('private_registration_option')
            teams = Teams.query.add_columns('name').all()
            registered_teams = {}

            for team in teams:
                registered_teams[team.name] = True

            invited_teams = InvitedTeams.query.order_by(
                InvitedTeams.id.asc()).all()

            for team in invited_teams:
                if team.name in registered_teams:
                    continue
                if selected_option == 'token':
                    token_text = ' with token {}'.format(team.token)
                else:
                    token_text = ''
                text = 'Team {} ({}) is invited for {}. You can register' \
                       'in {}{}.'.format(
                    team.name,
                    team.email,
                    utils.get_config('ctf_name'),
                    url_for('auth.register', _external=True),
                    token_text
                )
            utils.sendmail(team.email, text)
            return '1'
        else:
            return '0'


    @app.route('/admin/invited_teams/send_invitation/<int:id>',
               methods=['POST'])
    @admins_only
    def send_invitation(id):
        if utils.can_send_mail():
            selected_option = utils.get_config('private_registration_option')
            team = InvitedTeams.query.add_columns(
                'name', 'email', 'token').filter_by(id=id).first()

            if selected_option == 'token':
                token_text = ' with token {}'.format(team.token)
            else:
                token_text = ''
            text = 'Team {} ({}) is invited for {}. You can register' \
                   'in {}{}.'.format(
                team.name,
                team.email,
                utils.get_config('ctf_name'),
                url_for('auth.register', _external=True),
                token_text
            )

            utils.sendmail(team.email, text)
            return '1'
        else:
            return '0'


    def private_register():
        if not utils.can_register():
            return redirect(url_for('auth.login'))
        if request.method == 'POST':
            selected_option = utils.get_config('private_registration_option')

            errors = []

            if selected_option == 'token':
                token = request.form['token']
                invited_team = InvitedTeams.query.add_columns(
                    'name', 'email').filter_by(token=token).first()
                if not invited_team:
                    errors.append('Invalid token')
            elif selected_option == 'email':
                email = request.form['email']
                invited_team = InvitedTeams.query.add_columns(
                    'name', 'email').filter_by(email=email).first()
                if not invited_team:
                    errors.append('Your email is not invited')
            else:
                errors.append('Something strange happened')

            if len(errors) == 0:
                team = Teams.query.add_columns('id').filter_by(
                    name=invited_team.name).first()
                if team:
                    errors.append('Already registered')

            password = request.form['password']

            pass_short = len(password) == 0
            pass_long = len(password) > 128

            if pass_short:
                errors.append('Pick a longer password')
            if pass_long:
                errors.append('Pick a shorter password')

            if len(errors) > 0:
                if selected_option == 'token':
                    return render_template('register.html',
                                           errors=errors,
                                           token=request.form['token'],
                                           password=request.form['password'])
                elif selected_option == 'email':
                    return render_template('register.html',
                                           errors=errors,
                                           email=request.form['email'],
                                           password=request.form['password'])
                else:
                    return render_template('register.html')
            else:
                with app.app_context():
                    name = invited_team.name
                    email = invited_team.email
                    team = Teams(name, email.lower(), password)
                    db.session.add(team)
                    db.session.commit()
                    db.session.flush()

                    session['username'] = team.name
                    session['id'] = team.id
                    session['admin'] = team.admin
                    session['nonce'] = utils.sha512(os.urandom(10))

                    if (utils.can_send_mail() and
                        utils.get_config('verify_emails')):
                        db.session.close()
                        logger = logging.getLogger('regs')
                        logger.warn('[{0}] {1} registered (UNCONFIRMED) ' \
                                    'with {2}'.format(
                                        time.strftime('%m/%d/%Y %X'),
                                        name.encode('utf-8'),
                                        email.encode('utf-8')))

                        utils.verify_email(team.email)

                        return redirect(url_for('auth.confirm_user'))
                    else:
                        if utils.can_send_mail():
                            utils.sendmail(email, "You've successfully " \
                                           "registered for {}".format(
                                               utils.get_config('ctf_name')))

            db.session.close()

            logger = logging.getLogger('regs')
            logger.warn('[{0}] {1} registered with {2}'.format(
                time.strftime('%m/%d/%Y %X'), name.encode('utf-8'),
                              email.encode('utf-8')))
            return redirect(url_for('challenges.challenges_view'))
        else:
            return render_template('register.html')


    if not utils.get_config('private_registration_option'):
        utils.set_config('private_registration_option', 'token')

    override_register_template()
    app.view_functions['auth.register'] = private_register
