'''
 ====================================================================
 Copyright (c) 2003-2016 Barry A Scott.  All rights reserved.

 This software is licensed as described in the file LICENSE.txt,
 which you should have received as part of this distribution.

 ====================================================================

    wb_scm_app.py

'''
import sys

import wb_app
import wb_platform_specific

import wb_scm_main_window
import wb_scm_preferences
import wb_scm_debug

import wb_git_ui_components
import wb_hg_ui_components
import wb_svn_ui_components

from PyQt5 import QtGui

class WbScmApp(wb_app.WbApp,
               wb_scm_debug.WbScmDebug):
    def __init__( self, args ):
        self.__git_debug = False

        wb_scm_debug.WbScmDebug.__init__( self )
        wb_app.WbApp.__init__( self, ('Scm', 'Workbench'), args, ['git.cmd'] )

    def optionParse( self, args ):
        if args[1] == '--git-debug':
            self.__git_debug = True
            del args[ 1 ]
            return True

        return False

    def extraDebugEnabled( self ):
        # tells wb_logging to turn on debug for git.cmd
        return self.__git_debug

    def setupScmDebug( self ):
        # turn on ScmPython debug is required
        import git
        import logging

        if self.__git_debug:
            git.Git.GIT_PYTHON_TRACE = 'full'
            git_log = logging.getLogger( 'git.cmd' )
            git_log.setLevel( logging.DEBUG )

        else:
            git.Git.GIT_PYTHON_TRACE = False

    def createPreferencesManager( self ):
        return wb_scm_preferences.PreferencesManager(
                    self.log,
                    wb_platform_specific.getPreferencesFilename() )

    def createMainWindow( self ):
        if self.prefs.font.face is not None:
            font = QtGui.QFont( self.prefs.font.face, self.prefs.font.point_size, 50, False )
            self.setFont( font )

        self.top_window = wb_scm_main_window.WbScmMainWindow( self,
            {'git': wb_git_ui_components.GitMainWindowComponents()
            ,'hg':  wb_hg_ui_components.HgMainWindowComponents()
            ,'svn': wb_svn_ui_components.SvnMainWindowComponents()} )

        return self.top_window
