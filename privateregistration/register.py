import logging
import time

from flask import (
    current_app as app, redirect, render_template, request, session, url_for
)

from hashlib import md5
from os import urandom

from .model import InvitedTeams

from CTFd.models import db, Teams

from CTFd import utils


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
                session['nonce'] = utils.sha512(urandom(10))

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
