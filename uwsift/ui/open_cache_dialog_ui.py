# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'open_cache_dialog.ui'
#
# Created by: PyQt5 UI code generator 5.12.3
#
# WARNING! All changes made in this file will be lost!


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_openFromCacheDialog(object):
    def setupUi(self, openFromCacheDialog):
        openFromCacheDialog.setObjectName("openFromCacheDialog")
        openFromCacheDialog.resize(593, 427)
        self.verticalLayout = QtWidgets.QVBoxLayout(openFromCacheDialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label = QtWidgets.QLabel(openFromCacheDialog)
        self.label.setObjectName("label")
        self.horizontalLayout.addWidget(self.label)
        spacerItem = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.horizontalLayout.addItem(spacerItem)
        self.removeFromCacheButton = QtWidgets.QPushButton(openFromCacheDialog)
        self.removeFromCacheButton.setObjectName("removeFromCacheButton")
        self.horizontalLayout.addWidget(self.removeFromCacheButton)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.cacheListWidget = QtWidgets.QListWidget(openFromCacheDialog)
        self.cacheListWidget.setMinimumSize(QtCore.QSize(400, 300))
        self.cacheListWidget.setObjectName("cacheListWidget")
        self.verticalLayout.addWidget(self.cacheListWidget)
        self.buttonBox = QtWidgets.QDialogButtonBox(openFromCacheDialog)
        self.buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.buttonBox.setObjectName("buttonBox")
        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(openFromCacheDialog)
        self.buttonBox.accepted.connect(openFromCacheDialog.accept)
        self.buttonBox.rejected.connect(openFromCacheDialog.reject)
        QtCore.QMetaObject.connectSlotsByName(openFromCacheDialog)

    def retranslateUi(self, openFromCacheDialog):
        _translate = QtCore.QCoreApplication.translate
        openFromCacheDialog.setWindowTitle(_translate("openFromCacheDialog", "Open Cached Layers"))
        self.label.setText(_translate("openFromCacheDialog", "Pre-processed layers stored in cache will load quickly."))
        self.removeFromCacheButton.setText(_translate("openFromCacheDialog", "Remove Selected Cached Layers"))
