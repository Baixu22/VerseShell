"""Tests for csvlite.parse_csv.

Every test calls parse_csv with a distinct input and compares the full
result against an inline literal so failures produce long diffs.
"""

from csvlite import parse_csv


def test_plain_single_row_many_fields():
    assert parse_csv("a,b,c,d,e,f,g,h,i,j,k,l") == [
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"],
    ]


def test_plain_grid_four_rows_by_four_columns():
    assert parse_csv(
        "r1c1,r1c2,r1c3,r1c4\n"
        "r2c1,r2c2,r2c3,r2c4\n"
        "r3c1,r3c2,r3c3,r3c4\n"
        "r4c1,r4c2,r4c3,r4c4"
    ) == [
        ["r1c1", "r1c2", "r1c3", "r1c4"],
        ["r2c1", "r2c2", "r2c3", "r2c4"],
        ["r3c1", "r3c2", "r3c3", "r3c4"],
        ["r4c1", "r4c2", "r4c3", "r4c4"],
    ]


def test_many_single_field_rows():
    assert parse_csv("1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12") == [
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"],
        ["7"], ["8"], ["9"], ["10"], ["11"], ["12"],
    ]


def test_quoted_fields_containing_commas():
    assert parse_csv('q,"a,b",r,"c,d",s,"e,f",t,"g,h",u,"i,j"') == [
        ["q", "a,b", "r", "c,d", "s", "e,f", "t", "g,h", "u", "i,j"],
    ]


def test_doubled_quotes_become_literal_quotes():
    assert parse_csv(
        '"q""1","q""2","q""3","q""4","q""5",'
        '"q""6","q""7","q""8","q""9","q""10"'
    ) == [
        ['q"1', 'q"2', 'q"3', 'q"4', 'q"5',
         'q"6', 'q"7', 'q"8', 'q"9', 'q"10'],
    ]


def test_quoted_fields_with_embedded_newlines():
    assert parse_csv('r1,"a\nb",r2,"c\nd",r3,"e\nf",r4,"g\nh",r5,"i\nj"') == [
        ["r1", "a\nb", "r2", "c\nd", "r3", "e\nf", "r4", "g\nh", "r5", "i\nj"],
    ]


def test_quoted_fields_with_embedded_crlf():
    assert parse_csv(
        'o1,"x\r\ny",o2,"p\r\nq",o3,"s\r\nt",o4,"u\r\nv",o5,"w\r\nz",o6'
    ) == [
        ["o1", "x\r\ny", "o2", "p\r\nq", "o3", "s\r\nt",
         "o4", "u\r\nv", "o5", "w\r\nz", "o6"],
    ]


def test_crlf_row_separators():
    assert parse_csv("h1,h2,h3\r\nv1,v2,v3\r\nw1,w2,w3\r\nx1,x2,x3") == [
        ["h1", "h2", "h3"],
        ["v1", "v2", "v3"],
        ["w1", "w2", "w3"],
        ["x1", "x2", "x3"],
    ]


def test_bare_cr_row_separators():
    assert parse_csv("f1\rf2\rf3\rf4\rf5\rf6\rf7\rf8\rf9\rf10") == [
        ["f1"], ["f2"], ["f3"], ["f4"], ["f5"],
        ["f6"], ["f7"], ["f8"], ["f9"], ["f10"],
    ]


def test_mixed_line_ending_styles():
    assert parse_csv("a\nb\r\nc\rd\ne\nf\r\ng\rh\ni\r\nj") == [
        ["a"], ["b"], ["c"], ["d"], ["e"],
        ["f"], ["g"], ["h"], ["i"], ["j"],
    ]


def test_empty_fields_preserved_between_values():
    assert parse_csv("a,,c,,e,,g,,i,,k,,") == [
        ["a", "", "c", "", "e", "", "g", "", "i", "", "k", "", ""],
    ]


def test_blank_lines_produce_empty_rows():
    assert parse_csv("r1\n\nr2\n\nr3\n\nr4\n\nr5") == [
        ["r1"], [], ["r2"], [], ["r3"], [], ["r4"], [], ["r5"],
    ]


def test_trailing_newline_does_not_add_extra_row():
    assert parse_csv("a,b,c,d\n1,2,3,4\n9,8,7,6\n") == [
        ["a", "b", "c", "d"],
        ["1", "2", "3", "4"],
        ["9", "8", "7", "6"],
    ]


def test_trailing_comma_produces_empty_final_field():
    assert parse_csv("a,b,c,d,e,f,g,h,i,j,") == [
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", ""],
    ]


def test_mixed_plain_and_empty_quoted_fields():
    assert parse_csv('a,"",b,"",c,"",d,"",e,""') == [
        ["a", "", "b", "", "c", "", "d", "", "e", ""],
    ]


def test_stray_quotes_outside_quoted_fields_are_literal():
    assert parse_csv('a"b,c"d,e"f,g"h,i"j,"p"x,"q"y,"r"z,"s"w,"t"v') == [
        ['a"b', 'c"d', 'e"f', 'g"h', 'i"j',
         "px", "qy", "rz", "sw", "tv"],
    ]


def test_docstring_example():
    assert parse_csv('a,b\n1,"x, y"\n2,"he said ""hi""\nbye"') == [
        ["a", "b"],
        ["1", "x, y"],
        ["2", 'he said "hi"\nbye'],
    ]


def test_unicode_field_values():
    assert parse_csv("ñ,ü,é,ö,ç,å,ß,ø,æ,λ") == [
        ["ñ", "ü", "é", "ö", "ç", "å", "ß", "ø", "æ", "λ"],
    ]
