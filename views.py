# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import os

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.shortcuts import render
from django.urls import reverse

from .DAO import DAO
from .ExternalExport import ExternalExport

from graphos.renderers import flot
from graphos.sources.simple import SimpleDataSource

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

# Display log in page
def loginview(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(username=username, password=password)
        if user:
            if user.is_active:
                login(request, user)
                return HttpResponseRedirect('/nut/')
            else:
                return render(request, 'emr/login.html', {
                    'wrongcrendentials': 'Your account is disabled.'
                })
        else:
            return render(request, 'emr/login.html', {
                'wrongcrendentials': 'Invalid username / password combination provided'
            })
    else:
        return render(request, 'emr/login.html', {'wrongcrendentials': ''})


# Log out
def logoutbutton(request):
    logout(request)
    return render(request, 'emr/login.html', {'wrongcrendentials': ''})


# Home page
@login_required
def index(request):
    template_name = 'emr/index.html'
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    # *TBC*#
    # Last ID not used anymore
    return render(request, template_name, {
        'edbtables': daoobject.tables_config_lite,
        'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
        'easyUser': daoobject.easy_user,
    })


# Display search results
@login_required
def results(request):
    template_name = 'emr/results.html'
    search_query = request.GET.get('searchstring')
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    regularsearch = render(request, template_name, {
        'searchresults': daoobject.search(search_query, '1'),
        'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
        'easyUser': daoobject.easy_user,
    })
    try:
        searchInt = int(search_query)
        searchStr = str(searchInt)
        zerosToAdd = 6-len(searchStr)
        IdToReturn = ''
        for i in xrange(zerosToAdd):
            IdToReturn = IdToReturn + '0'
        if daoobject.doesIdExist(IdToReturn + searchStr):
            return patient(request, daoobject.doesIdExist(IdToReturn + searchStr))
        else:
            return regularsearch
    except ValueError:
        return regularsearch


# Display patient summary
@login_required
def patient(request, record_id):
    template_name = 'emr/patient.html'
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    daoobject.set_graphs(record_id)
    # Initialise graphos chart objects
    charts = []
    for graph in daoobject.graphs:
        charts.append([
            graph[0],
            flot.LineChart(
                SimpleDataSource(data=graph[3]),
                options={
                    'title': graph[2] + ' / ' + graph[1],
                    'xaxis': {'mode': "time", 'timezone': 'browser'},
                    'bars': {'barWidth': 86400000},
                    'legend': {'show': False, 'position': 'sw'},
                    'grid': {
                        'borderWidth': {'top': 0, 'right': 0, 'bottom': 2, 'left': 2},
                        'borderColor': {'bottom': "#999", 'left': "#999"},
                        'hoverable': True
                    },
                    'tooltip': {'show': True, 'content': '%x: %y'},
                }
            )
        ])
    daoobject.get_record_with_type('1', record_id, True)
    daoobject.get_related_records(record_id)
    daoobject.getLastId('tabla_1', 'campo_1')

    return render(request, template_name, {
        'record': daoobject.get_record_with_type('1', record_id, True),
        'relatedrecords': daoobject.get_related_records(record_id),
        'charts': charts,
        'graphs': daoobject.graphs,
        'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
        'easyUser': daoobject.easy_user,
    })


# View a specific record
@login_required
def detail(request, table_id, record_id):
    template_name = 'emr/detail.html'
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if daoobject.backEndUserRolesCheck(table_id, 'view_table'):
        return render(request, template_name, {
            'record': daoobject.get_record_with_type(table_id, record_id, False),
            'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
            'easyUser': daoobject.easy_user,
        })
    return index(request)


# Edit a record
@login_required
def edit(request, table_id, record_id):
    template_name = 'emr/edit.html'
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if daoobject.backEndUserRolesCheck(table_id, 'edit_table'):
        return render(request, template_name, {
            'record': daoobject.get_record_with_type(table_id, record_id, False),
            'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
            'easyUser': daoobject.easy_user,
        })
    return index(request)


# Save a record
@login_required
def save(request):
    record_id = request.POST.get('record_id')
    table_id = request.POST.get('table_id')
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    fieldstochange = []
    patientId = 0
    # *TBC*#
    # Lost of nested loops
    for tablec in daoobject.tables_config:
        if tablec['id'] == table_id:
            for fieldc in tablec['fields']:
                if fieldc['name'] == 'MSF ID':
                    patientId = daoobject.getPatientIdFromMsfId(request.POST.get(fieldc['field_id']))
                fieldstochange.append([fieldc['field_id'], request.POST.get(fieldc['field_id']), fieldc['type']])
            fieldstochange.append(['user', request.user.username, '2'])
    if record_id != "0":
        if daoobject.backEndUserRolesCheck(table_id, 'edit_table'):
            daoobject.editrecord(table_id, record_id, fieldstochange)
    else:
        if daoobject.backEndUserRolesCheck(table_id, 'add_table'):
            record_id = daoobject.insertrecord(table_id, fieldstochange)
            if table_id == '1':
                patientId = record_id
    return HttpResponseRedirect(reverse('emr:patient', args=(patientId,)))


# Add a new record
@login_required
def addrecord(request, table_id, related_record_entry):
    template_name = 'emr/addrecord.html'
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if daoobject.backEndUserRolesCheck(table_id, 'add_table'):
        if (related_record_entry == '0') and (table_id == '1'):
            related_record_field = 'campo_1'
        else:
            related_record_field = 'campo_2'
        if table_id != "0":
            return render(request, template_name, {
                'recordform': daoobject.getrecordform(table_id),
                'related_record_entry': related_record_entry,
                'related_record_field': related_record_field,
                'lastId': daoobject.getLastId('tabla_1', 'campo_1'),
                'easyUser': daoobject.easy_user,
            })
    return index(request)


# Delete a record
@login_required
def deleterecord(request, table_id, record_id):
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if daoobject.backEndUserRolesCheck(table_id, 'delete_table'):
        daoobject.delete(table_id, record_id)
    return index(request)


# Download raw export
@login_required
def downloadexport(request):
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    # If user is in group "Admin"
    if request.user.groups.filter(id=2).exists():
        zip = daoobject.generateExport()+'.zip'
        if os.path.exists(zip):
            with open(zip, 'rb') as fh:
                response = HttpResponse(fh.read(), content_type="application/zip")
                response['Content-Disposition'] = 'inline; filename=' + os.path.basename(zip)
                return response
        raise Http404
    else:
        return index(request)


# Download single-file export
@login_required
def downloadsfexport(request):
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if request.user.groups.filter(id=2).exists():
        zip = daoobject.generateSingleFileExport()+'.zip'
        if os.path.exists(zip):
            with open(zip, 'rb') as fh:
                response = HttpResponse(fh.read(), content_type="application/zip")
                response['Content-Disposition'] = 'inline; filename=' + os.path.basename(zip)
                return response
        raise Http404
    else:
        return index(request)


# Download backup
@login_required
def downloadbackup(request):
    daoobject = DAO()
    daoobject = getTableConfigandUser(request, daoobject)
    if request.user.groups.filter(id=2).exists():
        file = u'/opt/shared/backup.gz.enc'
        if os.path.exists(file):
            with open(file, 'rb') as fh:
                response = HttpResponse(fh.read(), content_type="application/zip")
                response['Content-Disposition'] = 'inline; filename=' + os.path.basename(file)
                return response
        raise Http404
    else:
        return index(request)


# Download list of absents
# *TBC*#
# This is a specific customization for a health center. Should not be here
@login_required
def downloadabsents(request):
    extE = ExternalExport()
    if request.user.groups.filter(id=2).exists():
        csv = extE.getAbsents()
        if os.path.exists(csv):
            with open(csv, 'rb') as fh:
                response = HttpResponse(fh.read(), content_type="text/csv")
                response['Content-Disposition'] = 'inline; filename=' + os.path.basename(csv)
                return response
        raise Http404
    else:
        return index(request)


# *TBC*#
# Same as up
@login_required
def downloaddefaulters(request):
    extE = ExternalExport()
    if request.user.groups.filter(id=2).exists():
        csv = extE.getDefaulters()
        if os.path.exists(csv):
            with open(csv, 'rb') as fh:
                response = HttpResponse(fh.read(), content_type="text/csv")
                response['Content-Disposition'] = 'inline; filename=' + os.path.basename(csv)
                return response
        raise Http404
    else:
        return index(request)

# Create sessions variables for expensive functions    
@receiver(user_logged_in)
def setTableConfigsAndUser(sender, user, request, **kwargs):
    daoobject = DAO()
    request.session['tableConfig'] = daoobject.set_tables_config()
    request.session['tableConfigLite'] = daoobject.tables_config_lite
    request.session['easyUser'] = daoobject.setEasyUser(request.user)
    return

def getTableConfigandUser(request, daoobject):
    if request.session['tableConfig'] and request.session['tableConfigLite']:
        daoobject.tables_config = request.session['tableConfig']
        daoobject.tables_config_lite = request.session['tableConfigLite']
    else:
        daoobject.set_tables_config()
    if request.session['easyUser']:
        daoobject.easy_user = request.session['easyUser']
    else:
        daoobject.setEasyUser(request.user)
    return daoobject
