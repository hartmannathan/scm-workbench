'''
 ====================================================================
 Copyright (c) 2016 Barry A Scott.  All rights reserved.

 This software is licensed as described in the file LICENSE.txt,
 which you should have received as part of this distribution.

 ====================================================================

    wb_hg_table_model.py

'''
from PyQt5 import QtGui
from PyQt5 import QtCore

import os
import time

class WbHgTableSortFilter(QtCore.QSortFilterProxyModel):
    def __init__( self, app, parent=None ):
        self.app = app
        super().__init__( parent )

        self.filter_text = ''

    def setFilterText( self, text ):
        self.filter_text = text
        self.invalidateFilter()

    def filterAcceptsRow( self, source_row, source_parent ):
        model = self.sourceModel()
        index = model.createIndex( source_row, WbHgTableModel.col_name )

        entry = model.data( index, QtCore.Qt.UserRole )
        if entry.ignoreFile():
            return False

        if self.filter_text != '':
            return self.filter_text.lower() in entry.name.lower()

        return True

    def lessThan( self, source_left, source_right ):
        model = self.sourceModel()
        left_ent = model.entry( source_left )
        right_ent = model.entry( source_right )

        column = source_left.column()

        if column == model.col_name:
            return left_ent.name < right_ent.name

        if column == model.col_state:
            # working changes
            left = left_ent.workingAsString()
            right = right_ent.workingAsString()
            if left != right:
                return left > right

            left = left_ent.isWorkingNew()
            right = right_ent.isWorkingNew()
            if left != right:
                return left < right

            # finally in name order
            return left_ent.name < right_ent.name

        if column == model.col_date:
            left = (left_ent.stat().st_mtime, left_ent.name)
            right = (right_ent.stat().st_mtime, right_ent.name)

            return left < right

        if column == model.col_type:
            left = (left_ent.is_dir(), left_ent.name)
            right = (right_ent.is_dir(), right_ent.name)

            return left < right

        assert False, 'Unknown column %r' % (source_left,)

    def indexListFromNameList( self, all_names ):
        if len(all_names) == 0:
            return []

        model = self.sourceModel()

        all_indices = []
        for row in range( self.rowCount( QtCore.QModelIndex() ) ):
            index = self.createIndex( row, 0 )
            entry = model.data( index, QtCore.Qt.UserRole )
            if entry.name in all_names:
                all_indices.append( index )

        return all_indices

class WbHgTableModel(QtCore.QAbstractTableModel):
    col_state = 0
    col_name = 1
    col_date = 2
    col_type = 3

    column_titles = [U_('State'), U_('Name'), U_('Date'), U_('Type')]

    def __init__( self, app ):
        self.app = app

        self._debug = self.app._debugTableModel

        super().__init__()

        self.hg_project_tree_node = None

        self.all_files = []

        self.__brush_working_new = QtGui.QBrush( QtGui.QColor( 0, 128, 0 ) )
        self.__brush_is_working_changed = QtGui.QBrush( QtGui.QColor( 0, 0, 255 ) )

    def rowCount( self, parent ):
        return len( self.all_files )

    def columnCount( self, parent ):
        return len( self.column_titles )

    def headerData( self, section, orientation, role ):
        if role == QtCore.Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                return T_( self.column_titles[section] )

            if orientation == QtCore.Qt.Vertical:
                return ''

        elif role == QtCore.Qt.TextAlignmentRole and orientation == QtCore.Qt.Horizontal:
            return QtCore.Qt.AlignLeft

        return None

    def entry( self, index ):
        return self.all_files[ index.row() ]

    def data( self, index, role ):
        if role == QtCore.Qt.UserRole:
            return self.all_files[ index.row() ]

        if role == QtCore.Qt.DisplayRole:
            entry = self.all_files[ index.row() ]

            col = index.column()

            if col == self.col_state:
                return entry.workingAsString()

            elif col == self.col_name:
                if entry.is_dir():
                    return entry.name + os.sep

                else:
                    return entry.name

            elif col == self.col_date:
                return entry.fileDate()

            elif col == self.col_type:
                return entry.is_dir() and 'Dir' or 'File'

            assert False

        elif role == QtCore.Qt.ForegroundRole:
            entry = self.all_files[ index.row() ]
            working = entry.workingAsString()

            if working != '':
                return self.__brush_is_working_changed

            if entry.isWorkingNew():
                return self.__brush_working_new

            return None

        #if role == QtCore.Qt.BackgroundRole:

        return None

    def setHgProjectTreeNode( self, hg_project_tree_node ):
        self.refreshTable( hg_project_tree_node )

    def refreshTable( self, hg_project_tree_node=None ):
        self._debug( 'WbHgTableModel.refreshTable( %r ) start' % (hg_project_tree_node,) )
        self._debug( 'WbHgTableModel.refreshTable() self.hg_project_tree_node %r' % (self.hg_project_tree_node,) )

        if hg_project_tree_node is None:
            hg_project_tree_node = self.hg_project_tree_node

        all_files = {}
        for dirent in os_scandir( str( hg_project_tree_node.absolutePath() ) ):
            entry = WbHgTableEntry( dirent.name )
            entry.updateFromDirEnt( dirent )
            
            all_files[ entry.name ] = entry

        for name in hg_project_tree_node.all_files.keys():
            if name not in all_files:
                entry = WbHgTableEntry( name )

            else:
                entry = all_files[ name ]

            entry.updateFromHg( hg_project_tree_node.getStatusEntry( name ) )

            all_files[ entry.name ] = entry

        if( self.hg_project_tree_node is None
        or self.hg_project_tree_node.isNotEqual( hg_project_tree_node ) ):
            self._debug( 'WbHgTableModel.refreshTable() resetModel' )
            self.beginResetModel()
            self.all_files = sorted( all_files.values() )
            self.endResetModel()

        else:
            parent = QtCore.QModelIndex()
            self._debug( 'WbHgTableModel.refreshTable() insert/remove' )

            all_new_files = sorted( all_files.values() )

            all_old_names = [entry.name for entry in self.all_files]
            all_new_names = [entry.name for entry in all_new_files]

            for offset in range( len(self.all_files) ):
                self._debug( 'old %2d %s' % (offset, all_old_names[ offset ]) )

            for offset in range( len(all_new_files) ):
                self._debug( 'new %2d %s' % (offset, all_new_names[ offset ]) )

            offset = 0
            while offset < len(all_new_files) and offset < len(self.all_files):
                self._debug( 'WbHgTableModel.refreshTable() while offset %d %s old %s' %
                        (offset, all_new_files[ offset ].name, self.all_files[ offset ].name) )
                if all_new_files[ offset ].name == self.all_files[ offset ].name:
                    if all_new_files[ offset ].isNotEqual( self.all_files[ offset ] ):
                        self._debug( 'WbHgTableModel.refreshTable() emit dataChanged row=%d' % (offset,) )
                        self.dataChanged.emit(
                            self.createIndex( offset, self.col_state ),
                            self.createIndex( offset, self.col_type ) )
                    offset += 1

                elif all_new_files[ offset ].name < self.all_files[ offset ].name:
                    self._debug( 'WbHgTableModel.refreshTable() insertRows row=%d %r' % (offset, all_new_names[offset]) )
                    self.beginInsertRows( parent, offset, offset )
                    self.all_files.insert( offset, all_new_files[ offset ] )
                    self.endInsertRows()
                    offset += 1

                else:
                    self._debug( 'WbHgTableModel.refreshTable() deleteRows row=%d %r' % (offset, all_old_names[ offset ]) )
                    # delete the old
                    self.beginRemoveRows( parent, offset, offset )
                    del self.all_files[ offset ]
                    del all_old_names[ offset ]
                    self.endRemoveRows()

            if offset < len(self.all_files):
                self._debug( 'WbHgTableModel.refreshTable() removeRows at end of old row=%d %r' % (offset, all_old_names[ offset: ]) )

                self.beginRemoveRows( parent, offset, len(self.all_files)-1 )
                del self.all_files[ offset: ]
                self.endRemoveRows()

            if offset < len(all_new_files):
                self._debug( 'WbHgTableModel.refreshTable() insertRows at end of new row=%d %r, old row %s' % (offset, all_new_names[offset:], offset) )

                to_insert = len(all_new_files) - offset - 1
                self.beginInsertRows( parent, offset, offset + to_insert )
                self.all_files.extend( all_new_files[offset:] )
                self.endInsertRows()

            self.all_files = sorted( all_files.values() )

        self.hg_project_tree_node = hg_project_tree_node
        self._debug( 'WbHgTableModel.refreshTable() done self.hg_project_tree_node %r' % (self.hg_project_tree_node,) )

class WbHgTableEntry:
    def __init__( self, name ):
        self.name = name
        self.dirent = None
        self.status = None

    def isNotEqual( self, other ):
        return (self.name != other.name
            or self.status != other.status
            or self.dirent != self.dirent)

    def updateFromDirEnt( self, dirent ):
        self.dirent = dirent

    def updateFromHg( self, status ):
        self.status = status

    def stat( self ):
        return self.dirent.stat()

    def __lt__( self, other ):
        return self.name < other.name

    def is_dir( self ):
        return self.dirent is not None and self.dirent.is_dir()

    def fileDate( self ):
        if self.dirent is None:
            return '-'

        else:
            return time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime( self.dirent.stat().st_mtime ) )

    def ignoreFile( self ):
        if self.status is None:
            return True

        return False

    def workingAsString( self ):
        if self.status is None:
            return ''

        return self.status.getAbbreviatedStatus()

    def isWorkingNew( self ):
        if self.status is None:
            return False

        # QQQ
        return False

def os_scandir( path ):
    if hasattr( os, 'scandir' ):
        return os.scandir( path )

    return [DirEntPre35( filename, path ) for filename in os.listdir( path )]

class DirEntPre35:
    def __init__( self, name, parent ):
        self.name = name
        self.__full_path = os.path.join( parent, name )
        self.__stat = os.stat( self.__full_path )

    def stat( self ):
        return self.__stat

    def is_dir( self ):
        import stat
        return stat.S_ISDIR( self.__stat.st_mode )