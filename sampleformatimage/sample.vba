Public sFunctionID As String
Public sFunctionName As String
Public sPathTemplate As String
Public sPathSrc As String
Public sPathSpec As String
Public sPathOut As String
Public flagInit As Boolean
Public sPathXlsmOut As String
Public sNameXlsmOut As String
Public flagErr As Boolean
Public zScreenUpdating As Variant

Sub ClearErr()
    ThisWorkbook.Worksheets("Err").Cells.Delete
End Sub

Sub addErr(ByVal sErr As Variant, Optional ByVal iColor As Variant = vbWhite)
    iEndRow = ThisWorkbook.Worksheets("Err").Cells( _
            ThisWorkbook.Worksheets("Err").Range("A1").SpecialCells(xlCellTypeLastCell).Row + 1, 1).End(xlUp).Row + 1
    ThisWorkbook.Worksheets("Err").Cells(iEndRow, 1) = ActiveWorkbook.Name
    ThisWorkbook.Worksheets("Err").Cells(iEndRow, 2) = ActiveSheet.Name
    ThisWorkbook.Worksheets("Err").Cells(iEndRow, 3) = "'" & sErr
    If (iColor <> vbWhite) Then
        ThisWorkbook.Worksheets("Err").Rows(iEndRow).Interior.Color = iColor
    End If
End Sub

Sub GetFolder(ByVal path As String, ByRef arrData As Variant)
    Set fso = CreateObject("Scripting.FileSystemObject")
    For Each fFile In fso.GetFolder(path).Files
        If (InStr(fFile.path, "~") = 0) Then
            ReDim Preserve arrData(UBound(arrData) + 1)
            arrData(UBound(arrData)) = fFile.path
        End If
    Next fFile
    For Each fFolder In fso.GetFolder(path).subfolders
        Call GetFolder(fFolder.path, arrData)
    Next fFolder
End Sub


Function FindFileSrc(ByVal sPattern As String, ByVal arrData As Variant, Optional ByVal flagErrAlert As Boolean = True) As String
    vTmpPattern = Split(sPattern, "*")
    iMaxFileSrc = UBound(arrData)
    iMaxPattern = UBound(vTmpPattern)
    sPathFind = Empty
    If (vTmpPattern(0) <> Empty) Then
        vTmpPattern(0) = "\" + vTmpPattern(0)
    End If
    For iTmp1 = 1 To iMaxFileSrc
        sPathFind = arrData(iTmp1)
        For iTmp2 = 0 To iMaxPattern
            If (vTmpPattern(iTmp2) <> Empty) Then
                If (InStr(arrData(iTmp1), vTmpPattern(iTmp2)) = 0) Then
                    sPathFind = Empty
                    Exit For
                End If
            End If
        Next iTmp2
        If (sPathFind <> Empty) Then
            Exit For
        End If
    Next iTmp1
    If (sPathFind = Empty And flagErrAlert) Then
        flagErr = True
    End If
    FindFileSrc = sPathFind
End Function

Function readFileInArrPath(ByVal sPattern As String, ByVal arrAllFile As Variant, Optional ByVal flagErrAlert As Boolean = True) As Variant

    sPathFileSeach = FindFileSrc(sPattern, arrAllFile, flagErrAlert)
    vFileSeach = readFile(sPathFileSeach)
    readFileInArrPath = vFileSeach
End Function


Function readFileLessCMInArrPath(ByVal sPattern As String, ByVal arrAllFile As Variant, Optional ByVal flagErrAlert As Boolean = True) As Variant

    sPathFileSeach = FindFileSrc(sPattern, arrAllFile, flagErrAlert)
    vFileSeach = readFile(sPathFileSeach)
    vFileSeach = GetLessComment(vFileSeach)
    readFileLessCMInArrPath = vFileSeach
End Function


Function GetLessComment(vFileSeach) As Variant
    vFileSeachOut = vFileSeach
    vFileSeachOut = RegExpReplaces(vFileSeachOut, "\/\*(?:[\s\S](?!\*\/))*[\s\S][\s\S]\*\/", "")
    vFileSeachOut = RegExpReplaces(vFileSeachOut, "\n^\s*\/\/.*$", "")
    GetLessComment = vFileSeachOut
End Function



'Function readFile(ByVal sPathFile As String) As Variant
'    Set fso = CreateObject("Scripting.FileSystemObject")
'    Set myFile = fso.OpenTextFile(sPathFile, 1, False, -2)
'    vMyFile = myFile.ReadAll
'    myFile.Close
'    Set myFile = Nothing
'    'Set fso = Nothing
'
'    Set myFile = fso.CreateTextFile(sPathOut & "\abc.txt", True, True)
'    myFile.Write vMyFile
'    myFile.Close
'    readFile = vMyFile
'End Function

Function readFile(ByVal sPathFile As String) As Variant
    If (sPathFile = Empty) Then
        readFile = Empty
        Exit Function
    End If
    Dim strData As Variant

    Dim objStream As Object

    Set objStream = CreateObject("ADODB.Stream")

    objStream.Charset = "utf-8"
    objStream.Open
    objStream.LoadFromFile (sPathFile)

    strData = objStream.ReadText()
'    strData = Replace(strData, Chr(13) & Chr(10), Chr(13))

    objStream.Close
    Set objStream = Nothing
    readFile = strData

End Function

Sub writeFile(ByVal sPathFile As String, ByVal sContent As String)
    Const adTypeText = 2
    Const adSaveCreateOverWrite = 2
    Dim objStream As Object
    Set objStream = CreateObject("ADODB.stream")

    objStream.Type = adTypeText
    objStream.Charset = "utf-8"
    objStream.Open

    objStream.WriteText sContent

    objStream.SaveToFile sPathFile, adSaveCreateOverWrite
    Set objStream = Nothing
End Sub

'Function readFile(ByVal sPathFile As String) As Variant
'    Dim text As Variant, textline As Variant
'    Open sPathFile For Input As #1
'    iCount = 1
'    Do Until EOF(1)
'        Line Input #1, textline
'        text = text & textline
'        iCount = iCount + 1
'    Loop
'    Close #1
'    readFile = text
'End Function

Function RegExpIsMatch(ByVal sInput As Variant, ByVal sPattern As Variant) As Boolean
    Dim RegEx As Object
    Set RegEx = CreateObject("VBScript.RegExp")
    RegEx.Pattern = sPattern
    RegEx.Global = False
    fMatch = RegEx.test(sInput)
    Set RegEx = Nothing
    RegExpIsMatch = fMatch
End Function


Function RegExpMatch(ByVal sInput As Variant, ByVal sPattern As Variant, Optional ByVal subGroupNo As Variant = -1) As Variant
    Dim RegEx As Object
    Set RegEx = CreateObject("VBScript.RegExp")
    RegEx.Pattern = sPattern
    RegEx.Global = False
    RegEx.IgnoreCase = True
    RegEx.MultiLine = True
    Set Matches = RegEx.Execute(sInput)
    sOutPut = Empty
    If (Matches.Count > 0) Then
        If (subGroupNo = -1) Then
            sOutPut = Matches(0).Value
        ElseIf (subGroupNo <= Matches.Count) Then
            sOutPut = Matches(0).SubMatches(subGroupNo)
        End If
    End If
    Set Matches = Nothing
    Set RegEx = Nothing
    RegExpMatch = sOutPut
End Function

Function RegExpMatches(ByVal sInput As Variant, ByVal sPattern As Variant) As Variant
    Dim RegEx As Object
    Set RegEx = CreateObject("VBScript.RegExp")
    RegEx.Pattern = sPattern
    RegEx.Global = True
    RegEx.IgnoreCase = True
    RegEx.MultiLine = True
    Set theMatches = RegEx.Execute(sInput)
    Set RegEx = Nothing
    Set RegExpMatches = theMatches
End Function

Function RegExpReplaces(ByVal sInput As Variant, ByVal sPattern As Variant, ByVal sPatternNew As Variant) As Variant
    Dim RegEx As Object
    Set RegEx = CreateObject("VBScript.RegExp")
    RegEx.Pattern = sPattern
    RegEx.Global = True
    RegEx.IgnoreCase = True
    RegEx.MultiLine = True
    sOutPut = RegEx.Replace(sInput, sPatternNew)
    Set RegEx = Nothing
    RegExpReplaces = sOutPut
End Function


Sub arrAdd(ByRef arrData As Variant, ByVal item As Variant)
    ReDim Preserve arrData(UBound(arrData) + 1)
    arrData(UBound(arrData)) = item
End Sub

Sub arrObjAdd(ByRef arrData As Variant, ByVal item As Object)
    ReDim Preserve arrData(UBound(arrData) + 1)
    Set arrData(UBound(arrData)) = item
End Sub

Sub arrExtern(ByRef arrData1 As Variant, ByVal arrData2 As Variant)
    For iTmp1 = 1 To UBound(arrData2)
        If (Not IsEmpty(arrData2(iTmp1))) Then
            Call arrAdd(arrData1, arrData2(iTmp1))
        End If
    Next iTmp1
End Sub



Sub arrSwapCol(ByRef arrDataIn As Variant, ByVal ColCheck As Variant, Optional ByVal ColCheck2 As Variant = 0)
    For iTmp1 = 1 To UBound(arrDataIn)
        sTmp1 = arrDataIn(iTmp1)(ColCheck)
        arrDataIn(iTmp1)(ColCheck) = arrDataIn(iTmp1)(ColCheck2)
        arrDataIn(iTmp1)(ColCheck2) = sTmp1
    Next iTmp1
End Sub

Sub arrAddSort(ByRef arrDataIn As Variant, ByVal ColCheck As Variant, Optional ByVal ColCheck2 As Variant = 0)
    Dim arrDataOut() As Variant
    ReDim arrDataOut(0)
    ' Call arrAdd(arrIfTmp, thatArrTmp)
    arrTmp = arrDataIn
    For iTmp1 = 1 To UBound(arrTmp)
        If (arrTmp(iTmp1)(0) <> Empty) Then
            ThisArr = arrTmp(iTmp1)
            Call arrAdd(arrDataOut, ThisArr)
            For iTmp2 = iTmp1 + 1 To UBound(arrTmp)
                thatArr = arrTmp(iTmp2)
                If (thatArr(0) = ThisArr(0)) Then
                    fSame = False
                    For iTmp3 = UBound(arrDataOut) To 1 Step -1
                        If (thatArr(0) <> arrDataOut(iTmp3)(0)) Then
                            Exit For
                        End If
                        If (thatArr(ColCheck) = arrDataOut(iTmp3)(ColCheck) And thatArr(ColCheck2) = arrDataOut(iTmp3)(ColCheck2)) Then
                            fSame = True
                            Exit For
                        End If
                    Next iTmp3
                    If (fSame = False) Then
                        Call arrAdd(arrDataOut, thatArr)
                    End If
                    arrTmp(iTmp2)(0) = Empty
                End If
            Next iTmp2
        End If
    Next iTmp1
    arrDataIn = arrDataOut
End Sub

Sub PrintArrTest(ByVal arrData As Variant, ByVal sheetName As Variant)
    ThisWorkbook.Worksheets(sheetName).Cells.ClearContents
    Dim rangedata() As Variant
    If (UBound(arrData) > 0) Then
        ReDim rangedata(1 To UBound(arrData), 1 To 100)
        For iTmp1 = 1 To UBound(arrData)
            If (Not IsEmpty(arrData(iTmp1))) Then
                For iTmp2 = 0 To UBound(arrData(iTmp1))
                    rangedata(iTmp1, iTmp2 + 1) = arrData(iTmp1)(iTmp2)
                Next iTmp2
            End If
        Next iTmp1

        ThisWorkbook.Worksheets(sheetName).Range(ThisWorkbook.Worksheets(sheetName).Cells(1, 1), ThisWorkbook.Worksheets(sheetName).Cells(UBound(rangedata, 1), UBound(rangedata, 2))) = rangedata
    End If
End Sub

Function SelectFolder() As Variant
    Dim sFolder As String
    ' Open the select folder prompt
    With Application.FileDialog(msoFileDialogFolderPicker)
        If .Show = -1 Then ' if OK is pressed
            sFolder = .SelectedItems(1)
        End If
    End With

    SelectFolder = sFolder
End Function


 ​Dim arrFile() As Variant
Dim sthisPath As Variant
Dim fCheck1Sheet As Boolean

Sub FixForMat_Click()
On Error GoTo ErrorCheck1
'    Application.ScreenUpdating = False
'    Application.Calculation = xlCalculationManual
'    Application.EnableEvents = False
    
    Dim answer As Integer
    
    answer = MsgBox("Yes : Format current sheet" & vbNewLine & "No : Format all sheet" & vbNewLine & "Cancel : Cancel", vbYesNoCancel)
    If answer = vbYes Then
        If InStr(1, ActiveSheet.Name, "•ÏX—š—ð", vbBinaryCompare) = 0 And InStr(1, ActiveSheet.Name, "ƒTƒ“ƒvƒ‹", vbBinaryCompare) = 0 Then
                
            Call FixForMatUTR(True)
            ActiveSheet.Range("A1").Select
            ActiveWindow.ScrollRow = 1
        Else
            MsgBox "Sai format sheet"
        End If
    ElseIf answer = vbNo Then
        Dim ws As Worksheet
        For Each ws In Worksheets
            ws.Activate
            If InStr(1, ws.Name, "•ÏX—š—ð", vbBinaryCompare) = 0 And InStr(1, ws.Name, "ƒTƒ“ƒvƒ‹", vbBinaryCompare) = 0 Then
                
                Call FixForMatUTR(True)
                ActiveSheet.Range("A1").Select
                ActiveWindow.ScrollRow = 1
                DoEvents
            End If
        Next ws
        Set ws = Nothing
    Else
'        Application.ScreenUpdating = True
'        Application.Calculation = xlCalculationAutomatic
'        Application.EnableEvents = True
        Exit Sub
    End If
    
'    Application.ScreenUpdating = True
'    Application.Calculation = xlCalculationAutomatic
'    Application.EnableEvents = True
    
    MsgBox "Finish"
    Exit Sub
ErrorCheck1:
'    Application.ScreenUpdating = True
'    Application.Calculation = xlCalculationAutomatic
'    Application.EnableEvents = True
    MsgBox "Format Fail"
End Sub

Sub FixForMatWithOutDraw_Click()
On Error GoTo ErrorCheck2
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual
    Application.EnableEvents = False
    Dim answer As Integer
    
    answer = MsgBox("Yes : Only Resize Image current sheet" & vbNewLine & "No : Only Resize Image all sheet" & vbNewLine & "Cancel : Cancel", vbYesNoCancel)
    If answer = vbYes Then
        If InStr(1, ActiveSheet.Name, "•ÏX—š—ð", vbBinaryCompare) = 0 And InStr(1, ActiveSheet.Name, "ƒTƒ“ƒvƒ‹", vbBinaryCompare) = 0 Then
            Call FixForMatUTR(False)
            ActiveSheet.Range("A1").Select
            ActiveWindow.ScrollRow = 1
        Else
            MsgBox "Sai format sheet"
        End If
    ElseIf answer = vbNo Then
        Dim ws As Worksheet
        For Each ws In Worksheets
            ws.Activate
            If InStr(1, ws.Name, "•ÏX—š—ð", vbBinaryCompare) = 0 And InStr(1, ws.Name, "ƒTƒ“ƒvƒ‹", vbBinaryCompare) = 0 Then
                Call FixForMatUTR(False)
                ActiveSheet.Range("A1").Select
                ActiveWindow.ScrollRow = 1
                DoEvents
            End If
        Next ws
        Set ws = Nothing
    Else
        Application.ScreenUpdating = True
        Application.Calculation = xlCalculationAutomatic
        Application.EnableEvents = True
        Exit Sub
    End If
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    Application.EnableEvents = True
    
    MsgBox "Finish"
    Exit Sub
ErrorCheck2:
    Application.ScreenUpdating = True
    Application.Calculation = xlCalculationAutomatic
    Application.EnableEvents = True
    MsgBox "Format Fail"
End Sub

Sub FixForMatUTR(ByVal drawFormat As Boolean)
On Error GoTo ErrorHandler
Application.ScreenUpdating = False
Application.Calculation = xlCalculationManual
Application.EnableEvents = False
    Dim oShapes As Shapes
    Dim oShape As Shape
    Dim dictTotal As Object
    Dim arrNewHT() As Variant
    Dim arrOldHT() As Variant
    Dim iColNew As Integer
    Dim iColOld As Integer
    Dim iColFist As Double
    
    ActiveWindow.Zoom = 100

    iColOld = 1
    iColNew = 19
    iColFist = 8.29
    
'    Cells.ColumnWidth = 8.29
'    Cells.RowHeight = 15.75

    
    Rows(1).RowHeight = 25.5
    Columns(1).ColumnWidth = iColFist
    Set oShapes = ActiveSheet.Shapes
    ReDim arrNewHT(0)
    ReDim arrOldHT(0)
    
    For Each oShape In oShapes
        oShape.Select
        If (InStr(LCase(oShape.Name), "picture") <> 0 Or InStr(LCase(oShape.Name), "}") <> 0) Then
            If (oShape.TopLeftCell.Column < iColNew) Then
                Call arrObjAdd(arrOldHT, oShape)
            Else
                Call arrObjAdd(arrNewHT, oShape)
                
            End If
            
        End If
        
    Next oShape
    
    Call SortArrHT(arrOldHT)
    Call SortArrHT(arrNewHT)
    
    If UBound(arrNewHT) > 0 Or UBound(arrOldHT) > 0 Then
        Set dictTotal = CreateObject("Scripting.Dictionary")
        Call SortAllHT(arrOldHT, arrNewHT, dictTotal)
        
        Call ShowArrHT(arrNewHT, iColNew, arrOldHT, iColOld, dictTotal)
'        If drawFormat = True Then
'            Call setBgColorCell
'            Call settingHeader
'        End If
     End If
    Set oShapes = Nothing
    Set oShape = Nothing
    Set dictTotal = Nothing
    Erase arrNewHT
    Erase arrOldHT
Application.ScreenUpdating = True
Application.Calculation = xlCalculationAutomatic
Application.EnableEvents = True
    Exit Sub
ErrorHandler:
    MsgBox "An error occurred: " & Err.Description
    Resume Next
End Sub

Sub SortAllHT(ByVal arrOldHT As Variant, ByVal arrNewHT As Variant, ByRef dictTotal As Object)
    Dim minRow As Long
    Dim maxRow As Long
    Dim index As Long
    Dim indexOld As Long
    Dim indexNew As Long
    Dim bottomRow As Long
    Dim imgRow As Long
    Dim imgCollection As Object
    Dim iMaxArrOld As Long
    Dim iMaxArrNew As Long
    Dim iMaxArr As Long
    
'    Dim newObject As Object
'    Dim oldObject As Object
    Dim stepRow As Long
    Dim outputRow As Long
    Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
    If Not foundCell Is Nothing Then
        stepRow = foundCell.Row
    End If
    Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
    If Not foundCell Is Nothing Then
        outputRow = foundCell.Row
    End If
    iMaxArrOld = UBound(arrOldHT)
    iMaxArrNew = UBound(arrNewHT)
    iMaxArr = WorksheetFunction.Max(iMaxArrNew, iMaxArrOld)

    index = 1
    indexOld = 1
    indexNew = 1

    maxRow = 1
    For iTmp1 = 1 To iMaxArrOld
        Set thisOldObject = arrOldHT(iTmp1)
        bottomRow = thisOldObject.BottomRightCell.Row
        If bottomRow > maxRow Then
            maxRow = bottomRow
        End If
    Next iTmp1
    
    For iTmp2 = 1 To iMaxArrNew
        Set thisNewObject = arrNewHT(iTmp2)
        bottomRow = thisNewObject.BottomRightCell.Row
        If bottomRow > maxRow Then
            maxRow = bottomRow
        End If
    Next iTmp2
    imgRow = 0
    
    Do While (imgRow <= maxRow)
        Set imgCollection = New Collection
        If (indexOld <= iMaxArrOld) Then
            Set oldObject = arrOldHT(indexOld)
            imgRow = oldObject.BottomRightCell.Row
        Else
            Set oldObject = Nothing
        End If
        
        If (indexNew <= iMaxArrNew) Then
            Set newObject = arrNewHT(indexNew)
            If imgRow > newObject.BottomRightCell.Row Then
                imgRow = newObject.BottomRightCell.Row
            End If
        Else
            Set newObject = Nothing
        End If
        
        If Not oldObject Is Nothing And Not newObject Is Nothing Then
            If (oldObject.BottomRightCell.Row < newObject.TopLeftCell.Row) Then
                imgCollection.Add (oldObject)
                imgCollection.Add Nothing
                indexOld = indexOld + 1
                dictTotal.Add index, imgCollection
            ElseIf (newObject.BottomRightCell.Row < oldObject.TopLeftCell.Row) Then
                imgCollection.Add Nothing
                imgCollection.Add (newObject)
                indexNew = indexNew + 1
                dictTotal.Add index, imgCollection
            Else
                
                If (newObject.TopLeftCell.Row < stepRow And oldObject.TopLeftCell.Row > stepRow) Then
                    MsgBox "Duplicate images found between Input and Steps areas. Please check again."
                    End
                End If
                
                If (newObject.TopLeftCell.Row < outputRow And oldObject.TopLeftCell.Row > outputRow) Then
                    MsgBox "Duplicate images found between Steps and Output areas. Please check again."
                    End
                End If
                
                imgCollection.Add (oldObject)
                imgCollection.Add (newObject)
                dictTotal.Add index, imgCollection
                indexOld = indexOld + 1
                indexNew = indexNew + 1
            End If
        ElseIf oldObject Is Nothing And Not newObject Is Nothing Then
                imgCollection.Add Nothing
                imgCollection.Add (newObject)
                indexNew = indexNew + 1
                dictTotal.Add index, imgCollection
        ElseIf Not oldObject Is Nothing And newObject Is Nothing Then
                imgCollection.Add (oldObject)
                imgCollection.Add Nothing
                indexOld = indexOld + 1
                dictTotal.Add index, imgCollection
        Else
            imgRow = maxRow + 1
        End If

        index = index + 1
        imgRow = imgRow + 1

    Loop
    Erase arrNewHT
    Erase arrOldHT
    Set imgCollection = Nothing
    Set thisOldObject = Nothing
    Set thisNewObject = Nothing
    Set oldObject = Nothing
    Set newObject = Nothing
End Sub

Sub ShowArrHT(ByVal arrNewHT As Variant, ByVal iColNew As Variant, ByVal arrOldHT As Variant, ByVal iColOut As Variant, ByVal dictTotal As Object)
    On Error GoTo ErrorHandler

    Application.WindowState = xlMaximized

    Dim iPicWidth As Integer
    Dim iPicWidthNew As Integer
    Dim iThisRow As Long
    Dim iMaxArrNew As Long
    Dim iMaxArrOld As Long
    Dim iMaxArr As Long
    Dim thisOldObject As Object
    Dim thisNewObject As Object
    Dim thisObject As Object
    Dim iThisEndOld As Long
    Dim iThisEndNew As Long
    Dim iThisEnd As Long
    Dim foundCell As Range
    Dim firstRow As Long
    Dim middleRow As Long
    Dim topImageRow As Long
    Dim isOutputArea As Boolean
    Dim isSteps As Boolean
    Dim data As Variant
    Dim tempRow As Long
    Dim stepRow As Long
    Dim errorCount As Integer
    errorCount = 0
    ' Calculate image widths for OLD and NEW areas
    iPicWidth = Range("C1:S1").Width       ' OLD: B to S (17 columns)
    iPicWidthNew = Range("V1:AL1").Width    ' NEW: V to AL (17 columns)
    
    iMaxArrNew = UBound(arrNewHT)
    iMaxArrOld = UBound(arrOldHT)
    iMaxArr = WorksheetFunction.Max(iMaxArrNew, iMaxArrOld)
    
    iThisRow = 1
    firstRow = 1
    middleRow = 1
    
    Set foundCell = Range("A:A").Find(What:="Input", LookIn:=xlValues, LookAt:=xlWhole)
    If Not foundCell Is Nothing Then
        firstRow = foundCell.Row
        iThisRow = foundCell.Row + 1
    End If
    
    
    Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
    If Not foundCell Is Nothing Then
        stepRow = foundCell.Row
        'iThisRow = foundCell.Row + 1
    End If
    
    Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
    If Not foundCell Is Nothing Then
        middleRow = foundCell.Row
    End If
    
    'Cells.Borders.LineStyle = xlNone
    Cells.Font.Name = "Meiryo UI"
    isOutputArea = False
    isSteps = False
    If dictTotal.Count > 0 Then
        For Each Key In dictTotal.Keys
            If Not IsEmpty(Key) Then
                Set thisOldObject = dictTotal(Key)(1)
                Set thisNewObject = dictTotal(Key)(2)
                
                If (thisNewObject Is Nothing) Then
                    Set thisObject = thisOldObject
                    
                    Application.CutCopyMode = False
                    thisObject.Width = iPicWidth
                    thisObject.Select
                    
                    topImageRow = Selection.TopLeftCell.Row
                    iThisEndOld = Selection.BottomRightCell.Row
                    If topImageRow >= firstRow Then
                        If (topImageRow > stepRow And isSteps = False) Then
                            If (iThisRow < stepRow - 1) Then
                                Rows(iThisRow & ":" & stepRow - 1).Delete
                                stepRow = stepRow - (stepRow - iThisRow)
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                            
                            iThisRow = stepRow
                            isSteps = True
                        Else
                            If iThisRow + (iThisEndOld - topImageRow) >= stepRow And isSteps = False Then
                                Rows(stepRow - topImageRow & ":" & stepRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    stepRow = foundCell.Row
                                End If
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        thisObject.Select
                        topImageRow = Selection.TopLeftCell.Row
                        If (topImageRow > middleRow And isOutputArea = False) Then
                            If (iThisRow < middleRow - 1) Then
                                Rows(iThisRow & ":" & middleRow - 1).Delete
                                middleRow = middleRow - (middleRow - iThisRow)
                            End If
                            
                            iThisRow = middleRow
                            isOutputArea = True
                        Else
                            If iThisRow + (iThisEndOld - topImageRow) >= middleRow And isOutputArea = False And isSteps = True Then
                                Rows(middleRow - topImageRow + stepRow & ":" & middleRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        'data = Range(Cells(iThisRow, 1), Cells(topImageRow, 10)).Value
                        tempRow = FindLastValueInRange(iThisRow, topImageRow)
                        If tempRow > 0 Then
                            iThisRow = tempRow
                        End If
                        
                        thisObject.Cut
                        Cells(iThisRow + 2, iColOut + 1).Select
                        ActiveSheet.Paste
                        Application.CutCopyMode = False
                        iThisEndOld = Selection.BottomRightCell.Row
                        
                        If isSteps = False Then
                            If iThisEndOld >= stepRow Then
                                Rows(stepRow & ":" & iThisEndOld + 2).Insert
                                stepRow = stepRow + (iThisEndOld - stepRow) + 3
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        If isOutputArea = False And isSteps = True Then
                            If iThisEndOld >= middleRow Then
                                Rows(middleRow & ":" & iThisEndOld + 2).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        
                    End If
                ElseIf (thisOldObject Is Nothing) Then
                    '=============New=============
                    Set thisObject = thisNewObject
        
                    Application.CutCopyMode = False
                    thisObject.Width = iPicWidthNew
                    thisObject.Select
                    
                    topImageRow = Selection.TopLeftCell.Row
                    If topImageRow >= firstRow Then
                        If (topImageRow > stepRow And isSteps = False) Then
                            If (iThisRow < stepRow - 1) Then
                                Rows(iThisRow & ":" & stepRow - 1).Delete
                                stepRow = stepRow - (stepRow - iThisRow)
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                            
                            iThisRow = stepRow
                            isSteps = True
                        Else
                            If iThisRow + (iThisEndNew - topImageRow) >= stepRow And isSteps = False Then
                                Rows(stepRow - topImageRow & ":" & stepRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    stepRow = foundCell.Row
                                End If
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        thisObject.Select
                        topImageRow = Selection.TopLeftCell.Row
                        If (topImageRow > middleRow And isOutputArea = False) Then
                            If (iThisRow < middleRow - 1) Then
                                Rows(iThisRow & ":" & middleRow - 1).Delete
                                middleRow = middleRow - (middleRow - iThisRow)
                            End If
                            
                            iThisRow = middleRow
                            isOutputArea = True
                        Else
                            If iThisRow + (iThisEndNew - topImageRow) >= middleRow And isOutputArea = False And isSteps = True Then
                                Rows(middleRow - topImageRow + stepRow & ":" & middleRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        'data = Range(Cells(iThisRow, 1), Cells(topImageRow, 10)).Value
                        tempRow = FindLastValueInRange(iThisRow, topImageRow)
                        If tempRow > 0 Then
                            iThisRow = tempRow
                        End If
                        
                        thisObject.Cut
                        Cells(iThisRow + 2, 21).Select
                        ActiveSheet.Paste
                        Application.CutCopyMode = False
                        iThisEndNew = Selection.BottomRightCell.Row
                        
                        If isSteps = False Then
                            If iThisEndNew >= stepRow Then
                                Rows(stepRow & ":" & iThisEndNew + 2).Insert
                                stepRow = stepRow + (iThisEndNew - stepRow) + 3
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        If isOutputArea = False And isSteps = True Then
                            If iThisEndNew >= middleRow Then
                                Rows(middleRow & ":" & iThisEndNew + 2).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        
                    End If
                Else
                    Set thisObject = thisOldObject
                    Application.CutCopyMode = False
                    thisObject.Width = iPicWidth
                    thisObject.Select
                    
                    topImageRow = Selection.TopLeftCell.Row
                    If topImageRow >= firstRow Then
'                        If (isSteps = False) Then
'                            'data = Range(Cells(iThisRow, 1), Cells(firstRow, 10)).Value
'                            tempRow = FindLastValueInRange(iThisRow, firstRow)
'                            If (tempRow < firstRow And tempRow > 0) Then
'                                Rows(tempRow & ":" & firstRow - 1).Delete
'                                firstRow = firstRow - (firstRow - tempRow)
'                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
'                                If Not foundCell Is Nothing Then
'                                    middleRow = foundCell.Row
'                                End If
'                                iThisRow = firstRow
'                                isSteps = True
'                            End If
'
'                        End If
                        
                        If (topImageRow > stepRow And isSteps = False) Then
                            If (iThisRow < stepRow - 1) Then
                                Rows(iThisRow & ":" & stepRow - 1).Delete
                                stepRow = stepRow - (stepRow - iThisRow)
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                            
                            iThisRow = stepRow
                            isSteps = True
                        Else
                            If iThisRow + (iThisEndOld - topImageRow) >= stepRow And isSteps = False Then
                                Rows(stepRow - topImageRow & ":" & stepRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    stepRow = foundCell.Row
                                End If
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        thisObject.Select
                        topImageRow = Selection.TopLeftCell.Row
                        If (topImageRow > middleRow And isOutputArea = False) Then
                            If (iThisRow < middleRow) Then
                                Rows(iThisRow & ":" & middleRow - 1).Delete
                                middleRow = middleRow - (middleRow - iThisRow)
                            End If
                            
                            iThisRow = middleRow
                            isOutputArea = True
                        Else
                            If iThisRow + (iThisEndOld - topImageRow) >= middleRow And isOutputArea = False And isSteps = True Then
                                Rows(middleRow - topImageRow + stepRow & ":" & middleRow).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        'data = Range(Cells(iThisRow, 1), Cells(topImageRow, 10)).Value
                        tempRow = FindLastValueInRange(iThisRow, topImageRow)
                        If tempRow > 0 Then
                            iThisRow = tempRow
                        End If
                        
                        thisObject.Cut
                        Cells(iThisRow + 2, iColOut + 1).Select
                        ActiveSheet.Paste
                        Application.CutCopyMode = False
                        iThisEndOld = Selection.BottomRightCell.Row
                        '=============New=============
            
                        Set thisObject = thisNewObject
            
                        Application.CutCopyMode = False
                        thisObject.Width = iPicWidthNew
                        thisObject.Select
                        thisObject.Cut
                        Cells(iThisRow + 2, 21).Select
                        ActiveSheet.Paste
                        Application.CutCopyMode = False
                        iThisEndNew = Selection.BottomRightCell.Row
                        If isSteps = False Then
                            If iThisEndOld >= stepRow Then
                                Rows(stepRow & ":" & iThisEndOld + 2).Insert
                                stepRow = stepRow + (iThisEndOld - stepRow) + 3
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
                        If isOutputArea = False And isSteps = True Then
                            If iThisEndOld >= middleRow Then
                                Rows(middleRow & ":" & iThisEndOld + 2).Insert
                                Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
                                If Not foundCell Is Nothing Then
                                    middleRow = foundCell.Row
                                End If
                            End If
                        End If
'                    Else
'                        If topImageRow - iThisRow > 3 Then
'                            'data = Range(Cells(iThisRow, 1), Cells(topImageRow, 10)).Value
'                            tempRow = FindLastValueInRange(iThisRow, topImageRow)
'                            If tempRow = 0 Then
'                                Rows(iThisRow & ":" & topImageRow - 2).Delete
'                            Else
'                                If topImageRow - tempRow > 3 Then
'                                    Rows(tempRow & ":" & topImageRow - 2).Delete
'                                End If
'                            End If
'
'                            Set foundCell = Range("A:A").Find(What:="Steps", LookIn:=xlValues, LookAt:=xlWhole)
'                            If Not foundCell Is Nothing Then
'                                firstRow = foundCell.Row
'                                'iThisRow = foundCell.Row + 1
'                            End If
'                            Set foundCell = Range("A:A").Find(What:="Output", LookIn:=xlValues, LookAt:=xlWhole)
'                            If Not foundCell Is Nothing Then
'                                middleRow = foundCell.Row
'                            End If
'                        End If
'
'                        thisOldObject.Width = iPicWidth
'                        thisNewObject.Width = iPicWidthNew
'
'                        thisOldObject.Select
'                        Cells(Selection.TopLeftCell.Row, iColOut + 1).Select
'                        thisOldObject.Cut
'                        ActiveSheet.Paste
'                        Application.CutCopyMode = False
'
'                        iThisEndOld = Selection.BottomRightCell.Row
'
'                        thisNewObject.Select
'                        Cells(Selection.TopLeftCell.Row, 21).Select
'                        thisNewObject.Cut
'                        ActiveSheet.Paste
'                        Application.CutCopyMode = False
'
'                        iThisEndNew = Selection.BottomRightCell.Row
'
'                        Range(Cells(Selection.TopLeftCell.Row, 20), Cells(Selection.BottomRightCell.Row + 2, 20)).Borders(xlEdgeLeft).LineStyle = xlContinuous
'                        Range(Cells(Selection.TopLeftCell.Row, 20), Cells(Selection.BottomRightCell.Row + 2, 20)).Borders(xlEdgeLeft).Weight = xlMedium

                    End If
        
                End If
                'If topImageRow > firstRow Then
                iThisEnd = WorksheetFunction.Max(iThisEndNew, iThisEndOld)
                iThisRow = iThisEnd + 2
                'End If
            End If
        Next
        
        Range(Cells(5, 20), Cells(iThisRow - 1, 20)).Borders(xlEdgeLeft).LineStyle = xlContinuous
        Range(Cells(5, 20), Cells(iThisRow - 1, 20)).Borders(xlEdgeLeft).Weight = xlMedium
        
        Range(Cells(5, 38), Cells(iThisRow - 1, 38)).Borders(xlEdgeRight).LineStyle = xlContinuous
        Range(Cells(5, 38), Cells(iThisRow - 1, 38)).Borders(xlEdgeRight).Weight = xlMedium
    
        Range(Cells(iThisRow - 1, 1), Cells(iThisRow - 1, 38)).Borders(xlEdgeBottom).LineStyle = xlContinuous
        Range(Cells(iThisRow - 1, 1), Cells(iThisRow - 1, 38)).Borders(xlEdgeBottom).Weight = xlMedium
        'Rows(iThisRow & ":" & 10000).Delete
        
    End If
    
    Erase arrNewHT
    Erase arrOldHT
    Set dictTotal = Nothing
    Set thisOldObject = Nothing
    Set thisNewObject = Nothing
    Set thisObject = Nothing
    Exit Sub
ErrorHandler:
    errorCount = errorCount + 1
    If errorCount > 5 Then
        MsgBox "An error occurred: " & Err.Description
        End
    Else
        Resume
    End If
    
End Sub

Function FindLastValueInRange(x As Long, y As Long) As Variant
    Dim lastRow As Long, lastCol As Long
    Dim lastValue As Variant
    Dim i As Long, j As Long
    Dim found As Boolean
    Dim data As Variant
    found = False
    data = Range(Cells(x, 1), Cells(y, 37)).Value
    For i = y To x Step -1
        For j = 1 To 10
            If data(i - x + 1, j) <> "" Then
                lastRow = i
                FindLastValueInRange = lastRow
                Exit Function
            End If
        Next j
    Next i
    
    FindLastValueInRange = 0
End Function

Sub SortArr(ByRef arrTmp As Variant)
    QuickSort arrTmp, LBound(arrTmp), UBound(arrTmp)
End Sub

Sub QuickSort(arr As Variant, ByVal first As Long, ByVal last As Long)
    Dim low As Long, high As Long, mid As Variant, temp As Variant
    low = first
    high = last
    mid = arr((first + last) \ 2)
    Do While (low <= high)
        Do While (arr(low) < mid)
            low = low + 1
        Loop
        Do While (arr(high) > mid)
            high = high - 1
        Loop
        If (low <= high) Then
            temp = arr(low)
            arr(low) = arr(high)
            arr(high) = temp
            low = low + 1
            high = high - 1
        End If
    Loop
    If (first < high) Then QuickSort arr, first, high
    If (low < last) Then QuickSort arr, low, last
End Sub

Sub SortArrHT(ByRef arrHT As Variant)
    Dim iMaxArr As Long
    Dim iTmp1 As Long
    Dim iTmp2 As Long
    Dim oTmp As Object
    
    iMaxArr = UBound(arrHT)
    
    For iTmp1 = 1 To iMaxArr - 1
        For iTmp2 = iTmp1 + 1 To iMaxArr
            If arrHT(iTmp1).TopLeftCell.Row > arrHT(iTmp2).TopLeftCell.Row Then
                Set oTmp = arrHT(iTmp1)
                Set arrHT(iTmp1) = arrHT(iTmp2)
                Set arrHT(iTmp2) = oTmp
            End If
        Next iTmp2
    Next iTmp1
    Set oTmp = Nothing
End Sub


Sub SetBgColorCell()
    Cells.Select
    With Selection.Interior
        .Pattern = xlSolid
        .PatternColorIndex = xlAutomatic
        .ThemeColor = xlThemeColorDark1
        .TintAndShade = 0
        .PatternTintAndShade = 0
    End With
    Range("A1:AJ1").Select
    With Selection.Interior
        .Pattern = xlSolid
        .PatternColorIndex = xlAutomatic
        .Color = 11389944
        .TintAndShade = 0
        .PatternTintAndShade = 0
    End With
End Sub

Sub settingHeader()
    ActiveSheet.Range("A1:R1").HorizontalAlignment = xlCenter
    ActiveSheet.Range("A1:R1").VerticalAlignment = xlCenter
    ActiveSheet.Range("A1:R1").Merge
    
    ActiveSheet.Range("S1:AJ1").HorizontalAlignment = xlCenter
    ActiveSheet.Range("S1:AJ1").VerticalAlignment = xlCenter
    ActiveSheet.Range("S1:AJ1").Merge
    
    ActiveSheet.Range("A1:R1").Value = "VƒVƒXƒeƒ€"
    ActiveSheet.Range("S1:AJ1").Value = "Œ»sƒVƒXƒeƒ€"
    
    ActiveSheet.Range("A1:AJ1").Font.Name = "Meiryo UI"
    ActiveSheet.Range("A1:AJ1").Font.Size = 22
    ActiveSheet.Range("A1:AJ1").Font.Bold = True
End Sub

Sub Macro2()
'
' Macro2 Macro
'

'
    Set a = Selection


    ActiveSheet.Pictures.Insert( _
        "D:\Projects\STAFFIA\FDN.DSI.NTTCWSTAFFIA\trunk\wip\04.Others\00.Tools\Staffia_ITC\Input\Old.png" _
        ).Select
    ActiveWindow.SmallScroll Down:=18
    ActiveWindow.Zoom = 55
    ActiveWindow.Zoom = 70
    ActiveWindow.Zoom = 55
    ActiveWindow.Zoom = 40
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 40
    Selection.ShapeRange.ScaleWidth 1.6548294957, msoFalse, msoScaleFromTopLeft
    Selection.ShapeRange.ScaleHeight 1.6548295568, msoFalse, msoScaleFromTopLeft
    Range("C68").Select
    ActiveSheet.Pictures.Insert( _
        "D:\Projects\STAFFIA\FDN.DSI.NTTCWSTAFFIA\trunk\wip\04.Others\00.Tools\Staffia_ITC\Input\New.png" _
        ).Select
    ActiveWindow.SmallScroll Down:=9
    Selection.ShapeRange.ScaleWidth 1.6512600414, msoFalse, msoScaleFromTopLeft
    Selection.ShapeRange.ScaleHeight 1.6512600574, msoFalse, msoScaleFromTopLeft
    Range("R6").Select
    ActiveWindow.SmallScroll Down:=-15
    Windows("FunctionID_FunctionName_Œ‹‡ƒeƒXƒgŽd—l‘_VN_v1.1.xlsx").Activate
    Windows("STAFFIA_MapSourceCodeAndFunction_V1.0.xlsx-rev4000.svn000.tmp.xlsx"). _
        Activate
    Windows("STAFFIA_MapSourceCodeAndFunction_V1.0.xlsx").Activate
    Sheets("FunctionMeasureLoc").Select
    Sheets("FunctionMeasureLoc").Name = "FunctionMeasureLoc_Update2"
    Windows("STAFFIA_MapSourceCodeAndFunction_V1.0.xlsx-rev4000.svn000.tmp.xlsx"). _
        Activate
    Sheets("FunctionMeasureLoc").Copy Before:=Workbooks( _
        "STAFFIA_MapSourceCodeAndFunction_V1.0.xlsx").Sheets(2)
    Sheets("FunctionMeasureLoc_Update2").Select
    Range("B2").Select
    ActiveCell.FormulaR1C1 = "LOC by funtion Update 2020/07/06:"
    Range("B3").Select
    Sheets("FunctionMeasureLoc_Update2").Select
    ActiveWindow.Close
    Range("A1").Select
    ActiveWorkbook.Save
    ActiveWindow.SmallScroll Down:=-24
    Range("G14").Select
    ActiveWindow.SmallScroll Down:=-39
    Range("A1").Select
    ActiveWorkbook.Save
    ActiveWorkbook.Save
    ActiveWindow.Close
    Range("S11").Select
    Sheets("FunctionMeasureLoc_Update2").Select
    Windows("(Ten file ITC)_ITE.xlsx").Activate
    Application.WindowState = xlNormal
    Windows("STAFFIA_MapSourceCodeAndFunction_V1.0.xlsx").Activate
    Windows("(Ten file ITC)_ITE.xlsx").Activate
    ActiveWindow.SmallScroll Down:=-42
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.ScaleWidth 0.2773275832, msoFalse, msoScaleFromTopLeft
    Selection.ShapeRange.ScaleHeight 0.2773275956, msoFalse, msoScaleFromTopLeft
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft 3.75
    Selection.ShapeRange.IncrementTop -663.75
    Selection.ShapeRange.ScaleWidth 0.2798264487, msoFalse, msoScaleFromTopLeft
    Selection.ShapeRange.ScaleHeight 0.2798264314, msoFalse, msoScaleFromTopLeft
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft 331.8750393701
    Selection.ShapeRange.IncrementTop -1.8749606299
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft 294.3749606299
    Selection.ShapeRange.IncrementTop 60
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft -73.1249606299
    Selection.ShapeRange.IncrementTop 684.3750393701
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft 33.75
    Selection.ShapeRange.IncrementTop -337.5
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft 56.25
    Selection.ShapeRange.IncrementTop -330
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 10
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft 1515
    Selection.ShapeRange.IncrementTop -742.5
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft 382.5
    Selection.ShapeRange.IncrementTop 1455
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft -1237.5
    Selection.ShapeRange.IncrementTop -277.5
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft 37.5
    Selection.ShapeRange.IncrementTop -967.5
    Selection.ShapeRange.IncrementLeft -210
    Selection.ShapeRange.IncrementTop 202.5
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft 4342.5
    Selection.ShapeRange.IncrementTop 397.5
    Range("HE82:HF86").Select
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft 4815
    Selection.ShapeRange.IncrementTop 1027.5
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft -4627.5
    Selection.ShapeRange.IncrementTop -22.5
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft -4575
    Selection.ShapeRange.IncrementTop -450
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 70
    ActiveWindow.Zoom = 85
    ActiveWindow.Zoom = 100
    ActiveWindow.Zoom = 85
    ActiveWindow.Zoom = 70
    ActiveWindow.Zoom = 55
    ActiveWindow.Zoom = 40
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 10
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft 75
    Selection.ShapeRange.IncrementTop -262.5
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft -127.5
    Selection.ShapeRange.IncrementTop 90
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft -187.5
    Selection.ShapeRange.IncrementTop -322.5
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 55
    ActiveWindow.SmallScroll Down:=24
    ActiveWindow.Zoom = 40
    ActiveWindow.Zoom = 25
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft 2265
    Selection.ShapeRange.IncrementTop -108
    ActiveSheet.Shapes.Range(Array("Picture 5")).Select
    Selection.ShapeRange.IncrementLeft 1953
    Selection.ShapeRange.IncrementTop -51
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft -2070
    Selection.ShapeRange.IncrementTop 207
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft -69
    Selection.ShapeRange.IncrementTop -291
    ActiveSheet.Shapes.Range(Array("Picture 5")).Select
    Selection.ShapeRange.IncrementLeft -285
    Selection.ShapeRange.IncrementTop -537
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    Selection.ShapeRange.IncrementLeft 468
    Selection.ShapeRange.IncrementTop -208.5
    Selection.ShapeRange.IncrementLeft -606
    Selection.ShapeRange.IncrementTop 108
    ActiveSheet.Shapes.Range(Array("Picture 5")).Select
    Selection.ShapeRange.IncrementLeft -1248
    Selection.ShapeRange.IncrementTop 36
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft -219
    Selection.ShapeRange.IncrementLeft 249
    Selection.ShapeRange.IncrementTop 174
    ActiveSheet.Shapes.Range(Array("Picture 5")).Select
    Selection.ShapeRange.IncrementLeft -378
    Selection.ShapeRange.IncrementTop 201
    ActiveSheet.Shapes.Range(Array("Picture 2")).Select
    Selection.ShapeRange.IncrementLeft -186
    Selection.ShapeRange.IncrementTop 393
    ActiveSheet.Shapes.Range(Array("Picture 5")).Select
    Selection.ShapeRange.IncrementLeft 15
    Selection.ShapeRange.IncrementTop 312
    Selection.ShapeRange.IncrementLeft -75
    Selection.ShapeRange.IncrementTop -201
    Range("F5").Select
    Selection.End(xlUp).Select
    Selection.End(xlToLeft).Select
    Selection.End(xlToRight).Select
    Selection.End(xlToLeft).Select
    Selection.End(xlToRight).Select
    Selection.End(xlToLeft).Select
    Selection.End(xlToRight).Select
    Selection.End(xlToLeft).Select
    Selection.Copy
    Selection.End(xlToRight).Select
    Application.CutCopyMode = False
    Selection.Copy
    Range("Z25").Select
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft 15
    Selection.ShapeRange.IncrementTop 1053
    Selection.ShapeRange.IncrementLeft 69
    Selection.ShapeRange.IncrementTop -996
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementTop 630
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft -201
    Selection.ShapeRange.IncrementTop 1386
    Range("AC49:AF90").Select
    Range("AF90").Activate
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft -210
    Selection.ShapeRange.IncrementTop -963
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft -6
    Selection.ShapeRange.IncrementTop -1005
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft 171
    Selection.ShapeRange.IncrementTop 1239
    Range("AK24:AK53").Select
    Range("AK53").Activate
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft 438
    Selection.ShapeRange.IncrementTop -513.75
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Selection.ShapeRange.IncrementLeft -240
    Selection.ShapeRange.IncrementTop -1107
    ActiveSheet.Shapes.Range(Array("Picture 4")).Select
    Selection.ShapeRange.IncrementLeft -369
    Selection.ShapeRange.IncrementTop 591
    Selection.ShapeRange.IncrementLeft 33
    Selection.ShapeRange.IncrementTop 324
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft 150
    Selection.ShapeRange.IncrementTop -750
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft 21
    Selection.ShapeRange.IncrementTop 294
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft -72
    Selection.ShapeRange.IncrementTop 738
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft -24
    Selection.ShapeRange.IncrementTop 306
    Selection.ShapeRange.Duplicate.Select
    Selection.ShapeRange.IncrementLeft -45
    Selection.ShapeRange.IncrementTop 237
End Sub
Sub Macro3()
'
' Macro3 Macro
'

'
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    ActiveSheet.Shapes.SelectAll
End Sub
Sub Macro4()
'
' Macro4 Macro
'

'
    Selection.ShapeRange.IncrementLeft -2.1429133858
    Selection.ShapeRange.IncrementTop -37.5
    ActiveWindow.SmallScroll Down:=3
    Selection.ShapeRange.IncrementLeft 175.7142519685
    Selection.ShapeRange.IncrementTop 282.8571653543
    Selection.Cut
    ActiveSheet.Paste
    Range("D8").Select
    ActiveWindow.SmallScroll Down:=-9
    Range("E5").Select
End Sub
Sub Macro5()
'
' Macro5 Macro
'

'
    Selection.Borders(xlDiagonalDown).LineStyle = xlNone
    Selection.Borders(xlDiagonalUp).LineStyle = xlNone
    Selection.Borders(xlEdgeLeft).LineStyle = xlContinuous
    Selection.Borders(xlEdgeLeft).Weight = xlThick
    With Selection.Borders(xlEdgeLeft).Weight = xlThick
        .LineStyle = xlContinuous
        .ColorIndex = 0
        .TintAndShade = 0
        .Weight = xlThick
    End With
    Selection.Borders(xlEdgeTop).LineStyle = xlNone
    Selection.Borders(xlEdgeBottom).LineStyle = xlNone
    Selection.Borders(xlEdgeRight).LineStyle = xlNone
    Selection.Borders(xlInsideVertical).LineStyle = xlNone
    Selection.Borders(xlInsideHorizontal).LineStyle = xlNone
End Sub
Sub Macro6()
'
' Macro6 Macro
'

'
    Sheets.Add After:=ActiveSheet
    Sheets.Add After:=ActiveSheet
End Sub
Sub Macro7()
'
' Macro7 Macro
'

'
    Set a = Selection
    Selection.ShapeRange.Fill.Visible = msoFalse



    ActiveSheet.Shapes.Range(Array("Rounded Rectangular Callout 9")).Select
    Selection.ShapeRange(1).TextFrame2.TextRange.Characters.Text = _
        "sadfsdafsdafdsafsdafs" & Chr(13) & "sadf" & Chr(13) & "sad" & Chr(13) & "fsad" & Chr(13) & "fsad" & Chr(13) & "fsadfasd"
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(1, 22). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(1, 22).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(23, 5). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(23, 5).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(28, 4). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(28, 4).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(32, 5). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(32, 5).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(37, 5). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(37, 5).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(42, 8). _
        ParagraphFormat
        .FirstLineIndent = 0
        .Alignment = msoAlignLeft
    End With
    With Selection.ShapeRange(1).TextFrame2.TextRange.Characters(42, 8).Font
        .NameComplexScript = "+mn-cs"
        .NameFarEast = "+mn-ea"
        .Fill.Visible = msoTrue
        .Fill.ForeColor.ObjectThemeColor = msoThemeColorLight1
        .Fill.ForeColor.TintAndShade = 0
        .Fill.ForeColor.Brightness = 0
        .Fill.Transparency = 0
        .Fill.Solid
        .Size = 24
        .Name = "+mn-lt"
    End With
End Sub


 Sub Macro1()
'
' Macro1 Macro
'

'
    ActiveSheet.Shapes.Range(Array("Picture 13")).Select
    Selection.Copy
    Range("AN66").Select
    ActiveSheet.Paste
    Selection.ShapeRange.IncrementLeft -521.25
    Selection.ShapeRange.IncrementTop -667.5
    Selection.ShapeRange.ZOrder msoSendToBack
    Range("FD70").Select
    ActiveSheet.Shapes.Range(Array("Picture 3")).Select
    ActiveSheet.Shapes.Range(Array("Picture 14")).Select
    ActiveSheet.Shapes.Range(Array("Picture 13")).Select
    ActiveWorkbook.Save
    ActiveSheet.Shapes.Range(Array("Picture 1")).Select
    Range("W11").Select
    ActiveWindow.Zoom = 85
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 40
    ActiveWindow.Zoom = 55
    ActiveWindow.Zoom = 70
    ActiveWindow.Zoom = 55
    ActiveWindow.Zoom = 40
    ActiveWindow.Zoom = 25
    ActiveWindow.Zoom = 10
    Sheets("UT_01").Select
    ActiveWindow.SelectedSheets.Delete
    Range("BT127").Select
    ActiveWindow.SmallScroll Down:=48
    Sheets("UT_01").Select
    ActiveWindow.SmallScroll Down:=-15
    Range("AA65").Select
    ActiveSheet.Shapes.Range(Array("picture 3")).Select
    Selection.ShapeRange.IncrementLeft -1.8749606299
    Selection.ShapeRange.IncrementTop 669.3750393701
    ActiveSheet.Shapes.Range(Array("picture 8")).Select
    Selection.ShapeRange.IncrementLeft -52.5
    Selection.ShapeRange.IncrementTop 588.75
    ActiveSheet.Shapes.Range(Array("picture 9")).Select
    Selection.ShapeRange.IncrementLeft 750
    Selection.ShapeRange.IncrementTop -945
    ActiveSheet.Shapes.Range(Array("picture 3")).Select
    Selection.ShapeRange.IncrementLeft 196.8750393701
    Selection.ShapeRange.IncrementTop -667.5
    Sheets("UT_01").Select
    ActiveWindow.SmallScroll Down:=-15
    Sheets("UT_02").Select
    ActiveWindow.SmallScroll Down:=18
    Range("GI131").Select
    ActiveWindow.SmallScroll Down:=36
    Sheets("UT_01").Select
    Range("GW38").Select
    ActiveWindow.SmallScroll Down:=45
    Sheets("UT_00").Select
    Range("AE90").Select
    ActiveWindow.SmallScroll Down:=-42
    Range("EW67").Select
    Sheets("UT_00").Select
    Range("AO82").Select
    Sheets("UT_01").Select
    ActiveWindow.SmallScroll Down:=-63
    Sheets("UT_02").Select
    Range("BA183").Select
    Sheets("UT_01").Select
    ActiveSheet.Shapes.Range(Array("picture 3")).Select
    Selection.Delete
    Sheets("UT_02").Select
    Range("GP129").Select
    ActiveWindow.SmallScroll Down:=3
    Sheets("UT_01").Select
    ActiveWindow.SmallScroll Down:=6
    Sheets("UT_02").Select
    Range("HB111").Select
    ActiveWindow.SmallScroll Down:=9
    Range("GT121").Select
    ActiveWindow.SmallScroll Down:=21
    Sheets("UT_01").Select
    ActiveWindow.SmallScroll Down:=-12
    Range("GE42").Select
    ActiveWindow.SmallScroll Down:=-18
    Windows("(Ten file ITC)_ITE.xlsm").Activate
    ActiveSheet.Shapes.Range(Array("picture 2")).Select
    Selection.Delete
    Sheets("UT_02").Select
    Range("GQ136").Select
    Sheets("UT_02").Select
    ActiveWindow.SmallScroll Down:=18
    ActiveSheet.Shapes.Range(Array("picture 4")).Select
    ActiveSheet.Shapes.Range(Array("picture 1")).Select
    ActiveSheet.Shapes.Range(Array("picture 4")).Select
    Range("GJ120").Select
    ActiveWindow.SmallScroll Down:=-102
    Range("GP14").Select
    ActiveWindow.SmallScroll Down:=-15
    Range("A1").Select
    ActiveSheet.Previous.Select
    Range("A1").Select
    ActiveSheet.Previous.Select
    ActiveWorkbook.Save
    Range("A1").Select
    ActiveWorkbook.Save
    ActiveWorkbook.Save
    ActiveWorkbook.Save
    Sheets("UT_02").Select
    ActiveWindow.SelectedSheets.Delete
    Sheets("UT_01").Select
    ActiveWindow.SelectedSheets.Delete
    ActiveSheet.Shapes.Range(Array("picture 1")).Select
    Selection.Copy
    Selection.Delete
    Range("F5").Select
    ActiveSheet.Paste
    ActiveSheet.Shapes.Range(Array("Picture 20")).Select
    Selection.ShapeRange.IncrementLeft 133.1250393701
    Selection.ShapeRange.IncrementTop 208.1249606299
    Range("AX6").Select
    Selection.NumberFormat = "h:mm"
    Selection.NumberFormat = "h:mm"
    Range("BW8").Select
    Selection.NumberFormat = "h:mm"
    Range("AW9").Select
    ActiveWorkbook.Save
End Sub

 Option Explicit

'GetSystemMetrics32 info: http://msdn.microsoft.com/en-us/library/ms724385(VS.85).aspx
#If Win64 Then
    Private Declare PtrSafe Function GetSystemMetrics32 Lib "User32" Alias "GetSystemMetrics" (ByVal nIndex As Long) As Long
#ElseIf Win32 Then
    Private Declare Function GetSystemMetrics32 Lib "User32" Alias "GetSystemMetrics" (ByVal nIndex As Long) As Long
#End If

'VBA Wrappers:
Public Function dllGetMonitors() As Long
    Const SM_CMONITORS = 80
    dllGetMonitors = GetSystemMetrics32(SM_CMONITORS)
End Function

Public Function dllGetHorizontalResolution() As Long
    Const SM_CXVIRTUALSCREEN = 78
    dllGetHorizontalResolution = GetSystemMetrics32(SM_CXVIRTUALSCREEN)
End Function

Public Function dllGetVerticalResolution() As Long
    Const SM_CYVIRTUALSCREEN = 79
    dllGetVerticalResolution = GetSystemMetrics32(SM_CYVIRTUALSCREEN)
End Function

Public Sub ShowDisplayInfo()
    Debug.Print "Total monitors: " & vbTab & vbTab & dllGetMonitors
    Debug.Print "Horizontal Resolution: " & vbTab & dllGetHorizontalResolution
    Debug.Print "Vertical Resolution: " & vbTab & dllGetVerticalResolution

    'Total monitors:         1
    'Horizontal Resolution:  1920
    'Vertical Resolution:    1080
End Sub
 


Sub Macro8()
'
' Macro8 Macro
'

'
    Range("V109:V121").Select
    Selection.Borders(xlDiagonalDown).LineStyle = xlNone
    Selection.Borders(xlDiagonalUp).LineStyle = xlNone
    Selection.Borders(xlEdgeLeft).LineStyle = xlNone
    Selection.Borders(xlEdgeTop).LineStyle = xlNone
    Selection.Borders(xlEdgeBottom).LineStyle = xlNone
    With Selection.Borders(xlEdgeRight)
        .LineStyle = xlContinuous
        .ColorIndex = xlAutomatic
        .TintAndShade = 0
        .Weight = xlMedium
    End With
    Selection.Borders(xlInsideVertical).LineStyle = xlNone
    Selection.Borders(xlInsideHorizontal).LineStyle = xlNone
    Range("W125").Select
End Sub
 


' Initialize the UserForm with default settings
Private Sub UserForm_Initialize()
    ' Default setting for radio buttons: blue color is selected by default
    OptionButtonBlue.Value = True  ' Default to Blue

End Sub
Sub ShowColorPopup()
    UserForm1.Show
End Sub
 