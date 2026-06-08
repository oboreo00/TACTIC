###########################################################
#
# Copyright (c) 2005, Southpaw Technology
#                     All Rights Reserved
#
# PROPRIETARY INFORMATION.  This software is proprietary to
# Southpaw Technology, and is not to be reproduced, transmitted,
# or disclosed in any way without written permission.
#
#
#

__all__ = ['CherryPyException', 'CherryPyAdapter', "get_app_server", "install_tactic_xmlrpc_error_handler"]


import types, os, re, sys

from pyasm.common import TacticException
from .web_environment import *

import cherrypy
from xmlrpc.client import Fault as XMLRPCFault, dumps as xmlrpc_dumps


# XML-RPC fault codes for API clients (msm-api-platform maps these to HTTP status).
FAULT_GENERAL = 1
FAULT_APPLICATION = 2
FAULT_AUTH = 401
FAULT_FORBIDDEN = 403
FAULT_NOT_FOUND = 404
FAULT_REMOTE = 5


def _resolve_xmlrpc_fault_code(exc):
    '''Map TACTIC exceptions to stable fault codes instead of always 1.'''
    if exc is None:
        return FAULT_GENERAL

    try:
        from pyasm.prod.service.api_xmlrpc import ApiException, RemoteApiException
    except ImportError:
        ApiException = type(None)
        RemoteApiException = type(None)

    try:
        from pyasm.common import SecurityException, SObjectSecurityException
    except ImportError:
        SecurityException = type(None)
        SObjectSecurityException = type(None)

    if isinstance(exc, RemoteApiException):
        return FAULT_REMOTE

    # SObjectSecurityException is row/column-level authorization: the caller IS
    # authenticated but is not permitted to touch this sObject -> 403 Forbidden.
    # It subclasses SecurityException, so it must be checked first.
    if isinstance(exc, SObjectSecurityException):
        return FAULT_FORBIDDEN

    # A plain SecurityException is TACTIC's authentication failure: wrong
    # login/password (get_ticket/get_ticket_data), expired/invalid ticket,
    # disabled user, unrecognized user, license issues, etc. These are "who are
    # you / your credentials are bad" -> 401 Unauthorized, which is what lets a
    # real wrong-password call surface as a genuine 401 instead of a 403.
    # A handful of SecurityException messages are really authorization rather
    # than authentication ("permission denied"); keep those as 403.
    if isinstance(exc, SecurityException):
        msg = str(exc).lower()
        if any(token in msg for token in (
            'permission denied',
            'access denied',
            'not allowed',
        )):
            return FAULT_FORBIDDEN
        return FAULT_AUTH

    if isinstance(exc, ApiException):
        msg = str(exc).lower()
        if any(token in msg for token in (
            'permission denied',
            'access denied',
            'not allowed',
            'wrong user',
        )):
            return FAULT_FORBIDDEN
        if any(token in msg for token in (
            'invalid_ticket',
            'invalid ticket',
            'api key not valid',
            'login',
            'authentication',
            'not authenticated',
        )):
            return FAULT_AUTH
        if 'does not exist' in msg:
            return FAULT_NOT_FOUND
        return FAULT_APPLICATION

    if isinstance(exc, TacticException):
        return FAULT_APPLICATION

    return FAULT_GENERAL


def tactic_xmlrpc_on_error(*args, **kwargs):
    '''CherryPy XML-RPC error hook with typed fault codes.'''
    exc_type, exc, tb = sys.exc_info()
    fault_code = _resolve_xmlrpc_fault_code(exc)
    if exc is not None:
        body = str(exc)
    elif exc_type is not None:
        body = exc_type.__name__
    else:
        body = "Unknown error"

    from cherrypy.lib import xmlrpcutil
    xmlrpcutil._set_response(xmlrpc_dumps(XMLRPCFault(fault_code, body)))


def install_tactic_xmlrpc_error_handler():
    '''Make TACTIC XML-RPC faults carry a typed code instead of always 1.

    CherryPy's XML-RPC error handler is the ErrorTool instance
    ``cherrypy.tools.xmlrpc``. That tool captured ``xmlrpcutil.on_error`` *by
    reference* when ``cherrypy._cptools`` was first imported, so reassigning the
    module-level ``xmlrpcutil.on_error`` alone is NOT enough -- the live tool
    keeps calling the stock handler (which always emits faultCode 1).

    ErrorTool reads ``self.callable`` dynamically at request time, so the
    reliable override is to reassign that attribute on the live tool. We also
    reassign the module-level hook so anything resolving it later sees ours too.

    If this install is disabled, set ``TACTIC_TYPED_FAULT_CODES=false`` on
    msm-api-platform so the API falls back to method/message heuristics.
    '''
    import cherrypy
    from cherrypy.lib import xmlrpcutil

    if getattr(xmlrpcutil, '_tactic_error_handler_installed', False):
        return

    # 1) Module-level hook (covers code paths that resolve it dynamically).
    xmlrpcutil.on_error = tactic_xmlrpc_on_error

    # 2) The live ErrorTool that actually services XML-RPC requests. This is the
    #    one that matters: it captured the stock on_error at import time.
    try:
        cherrypy.tools.xmlrpc.callable = tactic_xmlrpc_on_error
    except Exception as e:
        print("WARNING: could not patch cherrypy.tools.xmlrpc.callable:", e)

    xmlrpcutil._tactic_error_handler_installed = True
    print("Installed TACTIC XML-RPC error handler (typed fault codes)")


install_tactic_xmlrpc_error_handler()


class CherryPyException(Exception):
    pass


def get_app_server():

    server_cls = os.environ.get("TACTIC_SERVER_CLS")
    if not server_cls:
        from .app_server import BaseAppServer
        base_cls = BaseAppServer
    elif server_cls == "pyasm.web.WidgetAppServer":
        from .widget_app_server import WidgetAppServer
        base_cls = WidgetAppServer
    else:
        from .simple_app_server import SimpleAppServer
        base_cls = SimpleAppServer

    class CherryPyAppServer(base_cls):

        def get_adapter(self):
            adapter = CherryPyAdapter()
            return adapter
            

        @cherrypy.expose()
        def index(self, **kwargs):
            self.hash = ()
            return self.get_display()


        # set the hash object as a list
        @cherrypy.expose()
        def default(self, *vpath, **kwargs):
            self.hash = vpath
            return self.get_display().encode()




    return CherryPyAppServer



def get_xmlrpc_server():
    '''dynamically load in an xmlrpc server'''

    from cherrypy import _cptools
    class XmlrpcServer(_cptools.XMLRPCController):
         def get_adapter(self):
            adapter = CherryPyAdapter()
            return adapter

    return XmlrpcServer



from .cherrypy_adapter import CherryPyAdapter as CherryPyAdapter20
class CherryPyAdapter(CherryPyAdapter20):
    """Encapsulates cherrypy environment. Implements the web interface"""

    def __init__(self):
        self.request = cherrypy.request
        self.response = cherrypy.response

        #self.request.wsgi_environ['REQUEST_URI'] = self.request.browser_url
        self.request.wsgi_environ['REQUEST_URI'] = cherrypy.url()


    def get_context_name(self):
        '''this includes all of the subdirectories as well as the main
        context. Preferabbly it gets the project_code. if not, site_code '''
        path = self.get_request_path()
        
        p = re.compile( r"/(tactic|projects)/?(\w+)/")
        m = p.search(path)
        if not m:
            return "default"

        from pyasm.security import Site
        site_obj = Site.get()
        path_info = site_obj.break_up_request_path(path)
        
        if path_info:
            context = path_info.get("project_code")
            
            if not context:
                context = path_info.get("site")
            
        else:
            context = m.groups()[1]

        return context


    def get_request_path(self):
        return self.request.path_info


    def get_request_method(self):
        return self.request.method

    def get_request(self):
        return self.request

    def get_request_headers(self):
        return self.request.headers


    def get_response(self):
        return self.response

    def set_header(self, name, value):
        self.response.headers[name] = value

    def get_response(self):
        return self.response

    def set_content_type(self, content_type):
        self.response.headers['Content-Type'] = content_type

    def get_content_type(self):
        return self.response.headers['Content-Type']



    def set_force_download(self, filename):
        self.response.headers['Content-Type'] = "application/force-download"
        self.response.headers['Content-Disposition'] = "attachment; filename=%s" % filename


    def set_csv_download(self, filename):
        filename = os.path.basename(filename)
        self.response.headers['Content-Type'] = "text/x-csv"
        self.response.headers['Content-Disposition'] = "attachment; filename=%s" % filename



    # form submission functions
    def reset_form(self):
        self.request.params = {}
   
    def get_form_keys(self):
        return self.request.params.keys()

    def has_form_key(self, key):
        return key in self.request.params

    def set_form_value(self, name, value):
        '''Set the form value to appear like it was submitted'''
        # protect from accidental null names.  This can occur when an
        # input widget has not name specified.
        if not name:
            return
        self.request.params[name] = value


    def get_form_data(self):
        return self.request.params



    # cookie functions

    def set_cookie(self, name, value):
        '''set a cookie'''
        cherrypy.response.cookie[name] = value
        cherrypy.response.cookie[name]['path'] = '/'
        cherrypy.response.cookie[name]['max-age'] = 120*3600


    def get_cookie(self, name):
        '''get a cookie'''
        try:
            return cherrypy.request.cookie[name].value
            
        except KeyError as e:
            return ""



    def get_cookies(self):
        '''get a cookies'''
        return cherrypy.request.cookie
            


    # environment functions
    """
    def get_env_keys(self):
        env = self.request.wsgi_environ
        return env.keys()



    def get_env(self, env_var):
        env = self.request.wsgi_environ
        return env.get(env_var)
    """



