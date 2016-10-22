'''
 ====================================================================
 Copyright (c) 2003-2016 Barry A Scott.  All rights reserved.

 This software is licensed as described in the file LICENSE.txt,
 which you should have received as part of this distribution.

 ====================================================================

    wb_scm_main_window.py

    Based on code from pysvn WorkBench

'''
import sys
import os
import pathlib
import difflib

# On OS X the packager missing this import
import sip

import wb_platform_specific
import wb_shell_commands
import wb_background_thread

ellipsis = '…'

from PyQt5 import Qt
from PyQt5 import QtWidgets
from PyQt5 import QtGui
from PyQt5 import QtCore

import wb_scm_version
import wb_scm_preferences_dialog
import wb_scm_table_view
import wb_scm_tree_view
import wb_scm_tree_model
import wb_scm_project_dialogs
import wb_scm_progress

import wb_shell_commands
import wb_main_window
import wb_preferences
import wb_tracked_qwidget

from wb_background_thread import thread_switcher

class WbScmMainWindow(wb_main_window.WbMainWindow):
    INIT_STATE_INCONSISTENT = 0 # cannot trust self variables to exist yet
    INIT_STATE_CONSISTENT = 1   # all self variables exist but bg thread reading project state
    INIT_STATE_COMPLETE = 2     # everything is setup

    def __init__( self, app, all_scm_types ):
        self.table_view = None

        self.__init_state = self.INIT_STATE_INCONSISTENT

        super().__init__( app, app._debug_options._debugMainWindow )

        # need to fix up how this gets translated
        title = T_( ' '.join( self.app.app_name_parts ) )

        win_prefs = self.app.prefs.main_window

        self.setWindowTitle( title )
        self.setWindowIcon( self.app.getAppQIcon() )

        # models and views
        self.__ui_active_scm_type = None

        # this will trigger selectionChanged that needs tree_model
        # that will call treeSelectionChanged_Bg before the world is set up
        self.table_view = wb_scm_table_view.WbScmTableView( self.app, self )
        self.__setupTreeViewAndModel()

        self.all_ui_components = {}
        for scm_type in all_scm_types:
            self.all_ui_components[ scm_type ] = self.app.getScmFactory( scm_type ).uiComponents()
            self.all_ui_components[ scm_type ].setMainWindow( self, self.table_view )

        # setup the chrome
        self.setupMenuBar( self.menuBar() )
        self.setupToolBar()
        self.setupStatusBar( self.statusBar() )

        self.__setupTreeContextMenu()
        self.__setupTableContextMenu()

        # tell all scm ui to hide all components
        for scm_type in self.all_ui_components:
            self.all_ui_components[ scm_type ].setTopWindow( self )
            self.all_ui_components[ scm_type ].hideUiComponents()

        geometry = win_prefs.geometry
        if geometry is not None:
            geometry = QtCore.QByteArray( geometry.encode('utf-8') )
            self.restoreGeometry( QtCore.QByteArray.fromHex( geometry ) )

        else:
            em = self.app.fontMetrics().width( 'm' )
            ex = self.app.fontMetrics().lineSpacing()
            self.resize( 100*em, 50*ex )

        # window major widgets
        self.filter_text = QtWidgets.QLineEdit()
        self.filter_text.setClearButtonEnabled( True )
        self.filter_text.setMaxLength( 256 )
        self.filter_text.setPlaceholderText( T_('Filter by name') )

        self.filter_text.textChanged.connect( self.table_view.setFilterText )

        self.branch_text = QtWidgets.QLineEdit()
        self.branch_text.setReadOnly( True )

        self.folder_text = QtWidgets.QLineEdit()
        self.folder_text.setReadOnly( True )

        # layout widgets in window
        self.v_split = QtWidgets.QSplitter()
        self.v_split.setOrientation( QtCore.Qt.Vertical )

        self.setCentralWidget( self.v_split )

        self.h_split = QtWidgets.QSplitter( self.v_split )
        self.h_split.setOrientation( QtCore.Qt.Horizontal )

        self.v_split_table = QtWidgets.QSplitter()
        self.v_split_table.setOrientation( QtCore.Qt.Vertical )

        self.h_filter_widget = QtWidgets.QWidget( self.v_split )
        self.h_filter_layout = QtWidgets.QGridLayout()

        row = 0
        self.h_filter_layout.addWidget( QtWidgets.QLabel( T_('Filter:') ), row, 0 )
        self.h_filter_layout.addWidget( self.filter_text, row, 1, 1, 3 )

        row += 1
        self.h_filter_layout.addWidget( QtWidgets.QLabel( T_('Branch:') ), row, 0 )
        self.h_filter_layout.addWidget( self.branch_text, row, 1 )

        self.h_filter_layout.addWidget( QtWidgets.QLabel( T_('Path:') ), row, 2 )
        self.h_filter_layout.addWidget( self.folder_text, row, 3 )

        self.h_filter_layout.setColumnStretch( 1, 1 )
        self.h_filter_layout.setColumnStretch( 3, 2 )

        self.h_filter_widget.setLayout( self.h_filter_layout )

        self.v_table_widget = QtWidgets.QWidget( self.v_split )
        self.v_table_layout = QtWidgets.QVBoxLayout()
        self.v_table_layout.addWidget( self.h_filter_widget )
        self.v_table_layout.addWidget( self.table_view )

        self.v_table_widget.setLayout( self.v_table_layout )

        self.h_split.addWidget( self.tree_view )
        self.h_split.addWidget( self.v_table_widget )

        self.v_split.addWidget( self.h_split )
        self.v_split.addWidget( self.app.logWidget() )

        # timer used to wait for focus to be set after app is activated
        self.timer_update_enable_states = QtCore.QTimer()
        self.timer_update_enable_states.timeout.connect( self.updateActionEnabledStates )
        self.timer_update_enable_states.setSingleShot( True )

        # all variables exist
        self.__init_state = self.INIT_STATE_CONSISTENT

    @thread_switcher
    def completeInit( self ):
        self._debug( 'completeInit()' )

        self.tree_view.setFocus()

        # set splitter position
        tree_size_ratio = 0.3
        width = sum( self.h_split.sizes() )
        tree_width = int( width * tree_size_ratio )
        table_width = width - tree_width
        self.h_split.setSizes( [tree_width, table_width] )

        yield from self.loadProjects_Bg()

        self.updateActionEnabledStates()

        if self.__ui_active_scm_type is not None:
            # force the UI into shape - like setup of columns in table view
            self.all_ui_components[ self.__ui_active_scm_type ].showUiComponents()

        # fully initialised and ready to use
        self.__init_state = self.INIT_STATE_COMPLETE

        self.log.debug( 'Debug messages are enabled' )

    @thread_switcher
    def loadProjects_Bg( self ):
        self.log.info( 'Loading projects' )
        # load up all the projects
        self.tree_view.setSortingEnabled( False )
        for project in self.app.prefs.getAllProjects():
            self.tree_model.addProject( project )

        # if there is a bookmark select that project
        # otherwise select the first project
        bookmark = self.app.prefs.last_position_bookmark
        if bookmark is not None:
            project = self.app.prefs.getProject( bookmark.project_name )
            index = self.tree_model.indexFromProject( project )

        else:
            index = self.tree_model.getFirstProjectIndex()

        self.tree_view.sortByColumn( 0, QtCore.Qt.DescendingOrder )
        self.tree_view.setSortingEnabled( True )

        if index is not None:
            index = self.tree_sortfilter.mapFromSource( index )
            self.tree_view.setCurrentIndex( index )

            # load in the project
            self.log.info( 'Loading selected project' )
            yield from self.updateTableView_Bg()

            if bookmark is not None:
                self.log.info( 'Restoring bookmark' )
                # move to bookmarked folder
                bm_index = self.tree_model.indexFromBookmark( bookmark )
                if bm_index is not None:
                    index = self.tree_sortfilter.mapFromSource( bm_index )
                    self.tree_view.setCurrentIndex( index )

            self.tree_view.scrollTo( index )

    def createProject( self, project ):
        if not project.path.exists():
            self.log.error( T_('Project %(name)s folder %(folder)s has been deleted') %
                            {'name': project.name
                            ,'folder': project.path} )
            return None

        if project.scm_type in self.all_ui_components:
            return self.all_ui_components[ project.scm_type ].createProject( project )

        else:
            self.app.log.error( 'Unsupported project type %r' % (project.scm,) )
            return None

    def __setupTreeViewAndModel( self ):
        self._debug( '__setupTreeViewAndModel' )

        self.tree_model = wb_scm_tree_model.WbScmTreeModel( self.app, self.table_view.table_model )

        self.tree_sortfilter = wb_scm_tree_model.WbScmTreeSortFilter( self.app, self )
        self.tree_sortfilter.setSourceModel( self.tree_model )
        self.tree_sortfilter.setDynamicSortFilter( False )

        self.tree_view = wb_scm_tree_view.WbScmTreeView( self.app, self )
        self.tree_view.setModel( self.tree_sortfilter )
        self.tree_view.setExpandsOnDoubleClick( True )
        self.tree_view.setSortingEnabled( True )

        # connect up signals
        self.tree_view.customContextMenuRequested.connect( self.treeContextMenu )
        self.tree_view.setContextMenuPolicy( QtCore.Qt.CustomContextMenu )

    singleton_update_table_running = False

    @thread_switcher
    def updateTableView_Bg( self ):
        if WbScmMainWindow.singleton_update_table_running:
            return

        WbScmMainWindow.singleton_update_table_running = True

        self._debug( 'updateTableView_Bg start' )
        # need to turn sort on and off to have the view sorted on an update
        self.tree_view.setSortingEnabled( False )

        # load in the latest status
        self._debug( 'updateTableView_Bg calling refreshTree_Bg' )
        yield from self.tree_model.refreshTree_Bg()

        # sort filter is now invalid
        self.table_view.table_sortfilter.invalidate()

        # tall all the singletons to update
        for singleton in self.app.getAllSingletons():
            singleton.updateSingleton()

        self.tree_view.setSortingEnabled( True )

        # enabled states will have changed
        self.timer_update_enable_states.start( 0 )
        self._debug( 'updateTableView_Bg done' )

        WbScmMainWindow.singleton_update_table_running = False

    def updateActionEnabledStates( self ):
        # can be called during __init__ on macOS version
        if self.table_view is None or self.table_view.table_model is None:
            return

        self.updateEnableStates()

    def setupMenuBar( self, mb ):
        # --- setup common menus
        m = mb.addMenu( T_('&File') )
        self._addMenu( m, T_('&Preferences…'), self.appActionPreferences, role=QtWidgets.QAction.PreferencesRole )
        self._addMenu( m, T_('View Log'), self.appActionViewLog )
        self._addMenu( m, T_('E&xit'), self.close, role=QtWidgets.QAction.QuitRole )

        m = mb.addMenu( T_('&View') )
        tv = self.table_view
        self._addMenu( m, T_('Show Controlled and Changed files'), tv.setShowControlledAndChangedFiles, checker=tv.checkerShowControlledAndChangedFiles )
        self._addMenu( m, T_('Show Controlled and Not Changed files'), tv.setShowControlledAndNotChangedFiles, checker=tv.checkerShowControlledAndNotChangedFiles )
        self._addMenu( m, T_('Show Uncontrolled files'), tv.setShowUncontrolledFiles, checker=tv.checkerShowUncontrolledFiles )
        self._addMenu( m, T_('Show Ignored files'), tv.setShowIgnoredFiles, checker=tv.checkerShowIgnoredFiles )

        m.addSeparator()

        self.diff_group = QtWidgets.QActionGroup( self )
        self.diff_group.setExclusive( True )
        self._addMenu( m, T_('Unified diff'), self.setDiffUnified, checker=self.checkerDiffUnified, group=self.diff_group )
        self._addMenu( m, T_('Side by side diff'), self.setDiffSideBySide, checker=self.checkerDiffSideBySide, group=self.diff_group )

        m = mb.addMenu( T_('F&older Actions') )
        self._addMenu( m, T_('&Command Shell'), self.treeActionShell, self.enablerFolderExists, 'toolbar_images/terminal.png' )
        self._addMenu( m, T_('&File Browser'), self.treeActionFileBrowse, self.enablerFolderExists, 'toolbar_images/file_browser.png' )

        m = mb.addMenu( T_('File &Actions') )
        self._addMenu( m, T_('Edit'), self.table_view.tableActionEdit, self.table_view.enablerTableFilesExists, 'toolbar_images/edit.png' )
        self._addMenu( m, T_('Open'), self.table_view.tableActionOpen, self.table_view.enablerTableFilesExists, 'toolbar_images/open.png' )

        # --- setup scm_type specific menus
        for scm_type in self.all_ui_components:
            self._debug( 'calling setupMenuBar for %r' % (scm_type,) )
            self.all_ui_components[ scm_type ].setupMenuBar( mb, self._addMenu )

        # --- setup menus less used common menus
        m = mb.addMenu( T_('&Project') )
        self._addMenu( m, T_('Add…'), self.projectActionAdd_Bg )
        self._addMenu( m, T_('Settings…'), self.projectActionSettings, self.enablerIsProject )
        self._addMenu( m, T_('Delete'), self.projectActionDelete, self.enablerIsProject )

        m = mb.addMenu( T_('&Help' ) )
        self._addMenu( m, T_("&About…"), self.appActionAbout, role=QtWidgets.QAction.AboutRole )

    def __setupTreeContextMenu( self ):
        self._debug( '__setupTreeContextMenu' )
        # --- setup scm_type specific menu
        for scm_type in self.all_ui_components:
            self._debug( 'calling setupTreeContextMenu for %r' % (scm_type,) )

            m = QtWidgets.QMenu( self )
            m.addSection( T_('Folder Actions') )
            self._addMenu( m, T_('&Command Shell'), self.treeActionShell, self.enablerFolderExists, 'toolbar_images/terminal.png' )
            self._addMenu( m, T_('&File Browser'), self.treeActionFileBrowse, self.enablerFolderExists, 'toolbar_images/file_browser.png' )

            self.all_ui_components[ scm_type ].setupTreeContextMenu( m, self._addMenu )

    def __setupTableContextMenu( self ):
        self._debug( '__setupTableContextMenu' )

        # --- setup scm_type specific menu
        for scm_type in self.all_ui_components:
            self._debug( 'calling setupTableContextMenu for %r' % (scm_type,) )

            m = QtWidgets.QMenu( self )

            m.addSection( T_('File Actions') )
            self._addMenu( m, T_('Edit'), self.table_view.tableActionEdit, self.table_view.enablerTableFilesExists, 'toolbar_images/edit.png' )
            self._addMenu( m, T_('Open'), self.table_view.tableActionOpen, self.table_view.enablerTableFilesExists, 'toolbar_images/open.png' )

            self.all_ui_components[ scm_type ].setupTableContextMenu( m, self._addMenu )

    def setupToolBar( self ):
        # --- setup scm_type specific tool bars
        for scm_type in self.all_ui_components:
            self._debug( 'calling setupToolBarAtLeft for %r' % (scm_type,) )
            self.all_ui_components[ scm_type ].setupToolBarAtLeft( self._addToolBar, self._addTool )

        # --- setup common toolbars
        t = self.tool_bar_tree = self._addToolBar( T_('tree') )
        self._addTool( t, T_('Command Shell'), self.treeActionShell, self.enablerFolderExists, 'toolbar_images/terminal.png' )
        self._addTool( t, T_('File Browser'), self.treeActionFileBrowse, self.enablerFolderExists, 'toolbar_images/file_browser.png' )

        t = self.tool_bar_table = self._addToolBar( T_('table') )
        self._addTool( t, T_('Edit'), self.table_view.tableActionEdit, self.table_view.enablerTableFilesExists, 'toolbar_images/edit.png' )
        self._addTool( t, T_('Open'), self.table_view.tableActionOpen, self.table_view.enablerTableFilesExists, 'toolbar_images/open.png' )

        # --- setup scm_type specific tool bars
        for scm_type in self.all_ui_components:
            self._debug( 'calling setupToolBarAtRight for %r' % (scm_type,) )
            self.all_ui_components[ scm_type ].setupToolBarAtRight( self._addToolBar, self._addTool )

    def setupStatusBar( self, s ):
        self.status_general = QtWidgets.QLabel()
        self.status_progress = QtWidgets.QLabel()
        self.status_action = QtWidgets.QLabel()

        self.status_progress.setFrameStyle( QtWidgets.QFrame.Panel|QtWidgets.QFrame.Sunken )
        self.status_action.setFrameStyle( QtWidgets.QFrame.Panel|QtWidgets.QFrame.Sunken )

        s.addWidget( self.status_general, 1 )
        s.addWidget( self.status_progress, 1 )
        s.addWidget( self.status_action, 1 )

        self.setStatusGeneral()
        self.setStatusAction()

        self.progress = wb_scm_progress.WbScmProgress( self.status_progress )

    def setStatusGeneral( self, msg=None ):
        if msg is None:
            msg = T_('Workbench')

        self.status_general.setText( msg )

    def setStatusAction( self, msg=None ):
        if msg is None:
            msg = T_('Ready')

        self.status_action.setText( msg )

    #------------------------------------------------------------
    #
    #   Accessors for main window held state
    #
    #------------------------------------------------------------
    def isScmTypeActive( self, scm_type ):
        return self.__ui_active_scm_type == scm_type

    def selectedScmProjectTreeNode( self ):
        if self.tree_model is None:
            return None

        return self.tree_model.selectedScmProjectTreeNode()

    #------------------------------------------------------------
    #
    #   Enabler handlers
    #
    #------------------------------------------------------------
    def enablerFolderExists( self ):
        scm_project_tree_node = self.selectedScmProjectTreeNode()
        if scm_project_tree_node is None:
            return False

        return scm_project_tree_node.absolutePath() is not None

    def enablerIsProject( self ):
        scm_project_tree_node = self.selectedScmProjectTreeNode()
        if scm_project_tree_node is None:
            return False

        return scm_project_tree_node.relativePath() == pathlib.Path( '.' )

    #------------------------------------------------------------
    #
    #   Event handlers
    #
    #------------------------------------------------------------
    def appActiveHandler( self ):
        self._debug( 'appActiveHandler()' )

        # avoid double init
        if self.__init_state != self.INIT_STATE_COMPLETE:
            return

        self.app.wrapWithThreadSwitcher( self.updateTableView_Bg, 'appActiveHandler' )()

    #------------------------------------------------------------
    #
    # app actions
    #
    #------------------------------------------------------------
    def appActionPreferences( self ):
        pref_dialog = wb_scm_preferences_dialog.WbScmPreferencesDialog( self.app, self )
        if pref_dialog.exec_():
            pref_dialog.savePreferences()
            self.app.writePreferences()

    def appActionViewLog( self ):
        wb_shell_commands.EditFile( self.app, wb_platform_specific.getHomeFolder(), [wb_platform_specific.getLogFilename()] )

    def appActionAbout( self ):
        all_about_info = []
        all_about_info.append( '%s %d.%d.%d' %
                                (' '.join( self.app.app_name_parts )
                                ,wb_scm_version.major, wb_scm_version.minor
                                ,wb_scm_version.patch) )
        all_about_info.append( '(%s)' % (wb_scm_version.commit,) )
        all_about_info.append( '' )
        all_about_info.append( 'Python %d.%d.%d %s %d' %
                                (sys.version_info.major
                                ,sys.version_info.minor
                                ,sys.version_info.micro
                                ,sys.version_info.releaselevel
                                ,sys.version_info.serial) )
        all_about_info.append( 'PyQt %s, Qt %s' % (Qt.PYQT_VERSION_STR, QtCore.QT_VERSION_STR) )

        for scm_type in self.all_ui_components:
            all_about_info.append( '' )
            all_about_info.extend( self.all_ui_components[ scm_type ].about() )

        all_about_info.append( '' )
        all_about_info.append( T_('Copyright Barry Scott (c) %s. All rights reserved') % (wb_scm_version.copyright_years,) )

        box = QtWidgets.QMessageBox( 
            QtWidgets.QMessageBox.Information,
            T_('About %s') % (' '.join( self.app.app_name_parts ),),
            '\n'.join( all_about_info ),
            QtWidgets.QMessageBox.Close,
            parent=self )
        box.exec_()

    def errorMessage( self, title, message ):
        box = QtWidgets.QMessageBox(
            QtWidgets.QMessageBox.Critical,
            title,
            message,
            QtWidgets.QMessageBox.Close,
            parent=self )
        box.exec_()

    def closeEvent( self, event ):
        self.appActionClose( close=False )

    def appActionClose( self, close=True ):
        self._debug( 'appActionClose()' )
        scm_project_tree_node = self.selectedScmProjectTreeNode()

        prefs = self.app.prefs
        if scm_project_tree_node is not None:
            bookmark = wb_preferences.Bookmark(
                        'last position',
                        scm_project_tree_node.project.projectName(),
                        scm_project_tree_node.relativePath() )

            prefs.last_position_bookmark = bookmark

        else:
            prefs.last_position_bookmark = None

        win_prefs = self.app.prefs.main_window
        win_prefs.geometry = self.saveGeometry().toHex().data()

        self.app.writePreferences()

        # close all open modeless windows
        wb_tracked_qwidget.closeAllWindows()

        if close:
            self.close()


    #------------------------------------------------------------
    #
    # project actions
    #
    #------------------------------------------------------------
    @thread_switcher
    def projectActionAdd_Bg( self, checked ):
        w = wb_scm_project_dialogs.WbScmAddProjectWizard( self.app )
        if w.exec_():
            ui_components = self.all_ui_components[ w.getScmType() ]

            if w.getAction() == w.action_init:
                # pre is a good place to setup progress and status
                ui_components.addProjectPreInitWizardHandler( w.name, w.getScmUrl(), w.getWcPath() )

                yield self.app.switchToBackground
                add_project = ui_components.addProjectInitWizardHandler_Bg( w.getWcPath() )
                yield self.app.switchToForeground

                # post is a good place to finalise progress and status
                ui_components.addProjectPostInitWizardHandler()

            elif w.getAction() == w.action_clone:
                # pre is a good place to setup progress and status
                ui_components.addProjectPreCloneWizardHandler( w.name, w.getScmUrl(), w.getWcPath() )

                yield self.app.switchToBackground
                # do the actual clone in the background
                add_project = ui_components.addProjectCloneWizardHandler_Bg( w.name, w.getScmUrl(), w.getWcPath() )

                yield self.app.switchToForeground
                # post is a good place to finalise progress and status
                ui_components.addProjectPostCloneWizardHandler()

            elif w.getAction() == w.action_add_existing:
                add_project = True

            if add_project:
                prefs = self.app.prefs
                project = wb_preferences.Project( w.name, w.getScmType(), w.getWcPath() )
                prefs.addProject( project )

                self.app.writePreferences()

                self.tree_view.setSortingEnabled( False )
                self.tree_model.addProject( project )
                index = self.tree_model.indexFromProject( project )
                index = self.tree_sortfilter.mapFromSource( index )
                self.tree_view.setCurrentIndex( index )
                # load in the project
                yield from self.updateTableView_Bg()
                self.tree_view.setSortingEnabled( True )

    def projectActionDelete( self ):
        tree_node = self.selectedScmProjectTreeNode()
        if tree_node is None:
            return

        project_name = tree_node.project.projectName()

        default_button = QtWidgets.QMessageBox.No

        title = T_('Confirm Delete Project')
        message = T_('Are you sure you wish to delete project %s') % (project_name,)

        rc = QtWidgets.QMessageBox.question( self, title, message, defaultButton=default_button )
        if rc == QtWidgets.QMessageBox.Yes:
            # remove from preferences
            self.app.prefs.delProject( project_name )
            self.app.writePreferences()

            # remove from the tree model under the old name
            self.tree_model.delProject( project_name )

            # setup on a new selection
            index = self.tree_model.getFirstProjectIndex()

            if index is not None:
                index = self.tree_sortfilter.mapFromSource( index )
                self.tree_view.setCurrentIndex( index )

    def projectActionSettings( self ):
        tree_node = self.selectedScmProjectTreeNode()
        if tree_node is None:
            return

        scm_project = self.table_view.selectedScmProject()
        old_project_name = tree_node.project.projectName()
        prefs_project = self.app.prefs.getProject( old_project_name )

        dialog = self.app.getScmFactory( self.__ui_active_scm_type ).projectSettingsDialog( self.app, self, prefs_project, scm_project )
        if dialog.exec_():
            dialog.updateProject()

            self.app.writePreferences()

            self.tree_view.setSortingEnabled( False )

            # remove from the tree model
            self.tree_model.delProject( old_project_name )

            # add under the new name
            self.tree_model.addProject( prefs_project )

            index = self.tree_model.indexFromProject( prefs_project )
            index = self.tree_sortfilter.mapFromSource( index )
            self.tree_view.setCurrentIndex( index )

            self.tree_view.setSortingEnabled( True )

    #------------------------------------------------------------
    #
    # view actions
    #
    #------------------------------------------------------------
    def setDiffUnified( self ):
        self.app.prefs.view.setDiffUnified()

    def setDiffSideBySide( self ):
        self.app.prefs.view.setDiffSideBySide()

    def checkerDiffUnified( self ):
        return self.app.prefs.view.isDiffUnified()

    def checkerDiffSideBySide( self ):
        return self.app.prefs.view.isDiffSideBySide()

    #------------------------------------------------------------
    #
    # tree actions
    #
    #------------------------------------------------------------
    def treeContextMenu( self, pos ):
        self._debug( 'treeContextMenu( %r )' % (pos,) )
        global_pos = self.tree_view.viewport().mapToGlobal( pos )

        if self.__ui_active_scm_type is not None:
            self.all_ui_components[ self.__ui_active_scm_type ].getTreeContextMenu().exec_( global_pos )

    @thread_switcher
    def treeSelectionChanged_Bg( self, selected, deselected ):
        if self.__init_state < self.INIT_STATE_CONSISTENT:
            return

        # set the table view to the selected item in the tree
        self._debug( 'treeSelectionChanged_Bg calling selectionChanged_Bg' )
        yield from self.tree_model.selectionChanged_Bg( selected, deselected )

        self.filter_text.clear()

        scm_project = self.table_view.selectedScmProject()
        if( scm_project is not None
        and self.__ui_active_scm_type != scm_project.scmType() ):
            if self.__ui_active_scm_type is not None:
                self._debug( 'treeSelectionChanged hiding UI for %s' % (self.__ui_active_scm_type,) )
                self.all_ui_components[ self.__ui_active_scm_type ].hideUiComponents()

            self._debug( 'treeSelectionChanged showing UI for %s' % (scm_project.scmType(),) )
            self.__ui_active_scm_type = scm_project.scmType()
            self.all_ui_components[ self.__ui_active_scm_type ].showUiComponents()

        if scm_project is None:
            self.branch_text.clear()

        else:
            self.branch_text.setText( scm_project.getBranchName() )

        self.updateActionEnabledStates()

        folder = self.table_view.selectedAbsoluteFolder()
        if folder is None:
             self.folder_text.clear()

        else:
            try:
                # try to convert to ~ form
                if wb_platform_specific.isWindows():
                    folder = folder.relative_to( wb_platform_specific.getHomeFolder() )
                    folder = '~\\%s' % (folder,)

                else:
                    folder = folder.relative_to( wb_platform_specific.getHomeFolder() )
                    folder = '~/%s' % (folder,)

            except ValueError:
                folder = str( folder )

            self.folder_text.setText( folder )

    def treeActionShell( self ):
        folder_path = self.table_view.selectedAbsoluteFolder()
        if folder_path is None:
            return

        wb_shell_commands.CommandShell( self.app, folder_path )

    def treeActionFileBrowse( self ):
        folder_path = self.table_view.selectedAbsoluteFolder()
        if folder_path is None:
            return

        wb_shell_commands.FileBrowser( self.app, folder_path )

    #------------------------------------------------------------
    #
    # table actions
    #
    #------------------------------------------------------------
    def tableContextMenu( self, global_pos ):
        self._debug( 'tableContextMenu( %r )' % (global_pos,) )

        if self.__ui_active_scm_type is not None:
            self.all_ui_components[ self.__ui_active_scm_type ].getTableContextMenu().exec_( global_pos )

    def callTreeOrTableFunction( self, fn_tree, fn_table ):
        if self.focusIsIn() == 'tree':
            return fn_tree()

        elif self.focusIsIn() == 'table':
            return fn_table()

        else:
            assert False, 'must be tree or table but is %r' % (self.focusIsIn(),)

    # like callTreeOrTableFunction with yield for use with thread switcher
    @thread_switcher
    def callTreeOrTableFunction_Bg( self, fn_tree, fn_table ):
        if self.focusIsIn() == 'tree':
            if wb_background_thread.requiresThreadSwitcher( fn_tree ):
                yield from fn_tree()

            else:
                return fn_tree()

        elif self.focusIsIn() == 'table':
            if wb_background_thread.requiresThreadSwitcher( fn_table ):
                yield from fn_table()

            else:
                return fn_table()

        else:
            assert False, 'must be tree or table but is %r' % (self.focusIsIn(),)

    def tableSelectedAbsoluteFiles( self ):
        tree_node = self.selectedScmProjectTreeNode()
        root = tree_node.project.projectPath()
        return [root / filename for filename in self.tableSelectedFiles()]
