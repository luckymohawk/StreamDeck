FasdUAS 1.101.10   ��   ��    k             l     ��  ��    y s Purpose: Finds a window by custom title. If found, activates it (and optionally runs a command IF it's a re-init).     � 	 	 �   P u r p o s e :   F i n d s   a   w i n d o w   b y   c u s t o m   t i t l e .   I f   f o u n d ,   a c t i v a t e s   i t   ( a n d   o p t i o n a l l y   r u n s   a   c o m m a n d   I F   i t ' s   a   r e - i n i t ) .   
  
 l     ��  ��    N H If not found, creates a new styled window and runs the initial command.     �   �   I f   n o t   f o u n d ,   c r e a t e s   a   n e w   s t y l e d   w i n d o w   a n d   r u n s   t h e   i n i t i a l   c o m m a n d .      l     ��  ��      Placeholders:     �      P l a c e h o l d e r s :      l     ��  ��    C = {{escaped_target_title}} - The custom title to look for/set.     �   z   { { e s c a p e d _ t a r g e t _ t i t l e } }   -   T h e   c u s t o m   t i t l e   t o   l o o k   f o r / s e t .      l     ��  ��    Z T {{initial_command_payload}} - The command to run if creating OR if re-initializing.     �   �   { { i n i t i a l _ c o m m a n d _ p a y l o a d } }   -   T h e   c o m m a n d   t o   r u n   i f   c r e a t i n g   O R   i f   r e - i n i t i a l i z i n g .      l     ��   !��     B < {{aps_bg_color}} - AppleScript color string for background.    ! � " " x   { { a p s _ b g _ c o l o r } }   -   A p p l e S c r i p t   c o l o r   s t r i n g   f o r   b a c k g r o u n d .   # $ # l     �� % &��   % > 8 {{aps_text_color}} - AppleScript color string for text.    & � ' ' p   { { a p s _ t e x t _ c o l o r } }   -   A p p l e S c r i p t   c o l o r   s t r i n g   f o r   t e x t . $  ( ) ( l     �� * +��   *  y {{force_run_command_if_found}} - "true" or "false" string. If "true" and window found, will run initial_command_payload.    + � , , �   { { f o r c e _ r u n _ c o m m a n d _ i f _ f o u n d } }   -   " t r u e "   o r   " f a l s e "   s t r i n g .   I f   " t r u e "   a n d   w i n d o w   f o u n d ,   w i l l   r u n   i n i t i a l _ c o m m a n d _ p a y l o a d . )  - . - l     ��������  ��  ��   .  /�� / l    0���� 0 O     1 2 1 k    3 3  4 5 4 I   	������
�� .miscactvnull��� ��� null��  ��   5  6 7 6 r   
  8 9 8 m   
 ��
�� 
msng 9 o      ���� 0 window_to_use   7  : ; : r     < = < m    ��
�� boovfals = o      ���� 0 found_existing_window   ;  > ? > l   ��������  ��  ��   ?  @ A @ Q    P B C D B X    A E�� F E Z   ' < G H���� G =  ' , I J I n   ' * K L K 1   ( *��
�� 
titl L o   ' (���� 	0 w_obj   J m   * + M M � N N 0 { { e s c a p e d _ t a r g e t _ t i t l e } } H k   / 8 O O  P Q P r   / 2 R S R o   / 0���� 	0 w_obj   S o      ���� 0 window_to_use   Q  T U T r   3 6 V W V m   3 4��
�� boovtrue W o      ���� 0 found_existing_window   U  X�� X  S   7 8��  ��  ��  �� 	0 w_obj   F 2   ��
�� 
cwin C R      �� Y��
�� .ascrerr ****      � **** Y o      ���� 0 find_err  ��   D I  I P�� Z��
�� .ascrcmnt****      � **** Z b   I L [ \ [ m   I J ] ] � ^ ^ j A S _ E r r o r   ( a c t i v a t e _ o r _ c r e a t e ) :   E r r o r   f i n d i n g   w i n d o w :   \ o   J K���� 0 find_err  ��   A  _ ` _ l  Q Q��������  ��  ��   `  a�� a Z   Q b c�� d b F   Q Z e f e o   Q R���� 0 found_existing_window   f >  U X g h g o   U V���� 0 window_to_use   h m   V W��
�� 
msng c k   ] � i i  j k j I  ] d�� l��
�� .ascrcmnt****      � **** l m   ] ` m m � n n j A S :   F o u n d   e x i s t i n g   w i n d o w   ' { { e s c a p e d _ t a r g e t _ t i t l e } } ' .��   k  o p o O   e w q r q k   i v s s  t u t I  i n������
�� .miscactvnull��� ��� null��  ��   u  v�� v r   o v w x w m   o p����  x 1   p u��
�� 
pidx��   r o   e f���� 0 window_to_use   p  y z y l  x x�� { |��   { s m If forced, or if we decide @ buttons *always* re-run their command when reactivated (after initial creation)    | � } } �   I f   f o r c e d ,   o r   i f   w e   d e c i d e   @   b u t t o n s   * a l w a y s *   r e - r u n   t h e i r   c o m m a n d   w h e n   r e a c t i v a t e d   ( a f t e r   i n i t i a l   c r e a t i o n ) z  ~�� ~ Z   x �  ��� �  =  x  � � � m   x { � � � � � < { { f o r c e _ r u n _ c o m m a n d _ i f _ f o u n d } } � m   { ~ � � � � �  t r u e � Z   � � � ����� � >  � � � � � m   � � � � � � � 6 { { i n i t i a l _ c o m m a n d _ p a y l o a d } } � m   � � � � � � �   � k   � � � �  � � � I  � ��� ���
�� .ascrcmnt****      � **** � m   � � � � � � � � A S :   F o r c i n g   c o m m a n d   ' { { i n i t i a l _ c o m m a n d _ p a y l o a d } } '   i n   f o u n d   w i n d o w   ' { { e s c a p e d _ t a r g e t _ t i t l e } } ' .��   �  ��� � O  � � � � � I  � ��� � �
�� .coredoscnull��� ��� ctxt � m   � � � � � � � 6 { { i n i t i a l _ c o m m a n d _ p a y l o a d } } � �� ���
�� 
kfil � 1   � ���
�� 
tcnt��   � o   � ����� 0 window_to_use  ��  ��  ��  ��   � I  � ��� ���
�� .ascrcmnt****      � **** � m   � � � � � � � � A S :   F o u n d   w i n d o w   ' { { e s c a p e d _ t a r g e t _ t i t l e } } '   a c t i v a t e d .   N o   c o m m a n d   r e - r u n .��  ��  ��   d k   � � �  � � � I  � ��� ���
�� .ascrcmnt****      � **** � m   � � � � � � � � A S :   W i n d o w   ' { { e s c a p e d _ t a r g e t _ t i t l e } } '   n o t   f o u n d   o r   f o r c e d   n e w .   C r e a t i n g   a n d   r u n n i n g   i n i t i a l   c o m m a n d .��   �  � � � r   � � � � � m   � ���
�� 
msng � o      ���� 0 new_terminal_entity   �  � � � Q   � � � � � � r   � � � � � I  � ��� ���
�� .coredoscnull��� ��� ctxt � m   � � � � � � � 6 { { i n i t i a l _ c o m m a n d _ p a y l o a d } }��   � o      ���� 0 new_terminal_entity   � R      �� ���
�� .ascrerr ****      � **** � o      ���� 0 errmsg errMsg��   � I  � ��� ���
�� .ascrcmnt****      � **** � b   � � � � � m   � � � � � � � v A S _ E r r o r   ( a c t i v a t e _ o r _ c r e a t e ) :   E r r o r   d o i n g   i n i t i a l   s c r i p t :   � o   � ����� 0 errmsg errMsg��   �  � � � I  � ��� ���
�� .sysodelanull��� ��� nmbr � m   � � � � ?�333333��   �  � � � l  � ���������  ��  ��   �  � � � r   � � � � � m   � ���
�� 
msng � o      ���� 0 final_target_window   �  � � � Q   �� � � � � Z   �� � � ��� � >  � � � � � o   � ����� 0 new_terminal_entity   � m   � ���
�� 
msng � k   o � �  � � � r    � � � n    � � � m  ��
�� 
pcls � o   ���� 0 new_terminal_entity   � o      ���� 0 new_entity_class   �  ��� � Z  o � � � � � =  � � � o  ���� 0 new_entity_class   � m  ��
�� 
ttab � Q  B � � � � r  " � � � n   � � � m  ��
�� 
cwin � o  ���� 0 new_terminal_entity   � o      ���� 0 final_target_window   � R      ������
�� .ascrerr ****      � ****��  ��   � Z *B � ����� � ?  *3 � � � l *1 ����� � I *1�� ���
�� .corecnte****       **** � 2 *-��
�� 
cwin��  ��  ��   � m  12����   � r  6> � � � 4 6:�� �
�� 
cwin � m  89����  � o      ���� 0 final_target_window  ��  ��   �  � � � = EJ � � � o  EH���� 0 new_entity_class   � m  HI��
�� 
cwin �  ��� � r  MT � � � o  MP���� 0 new_terminal_entity   � o      ���� 0 final_target_window  ��   � Z Wo � ����� � ?  W` � � � l W^ ���� � I W^�~ ��}
�~ .corecnte****       **** � 2 WZ�|
�| 
cwin�}  ��  �   � m  ^_�{�{   � r  ck � � � 4 cg�z �
�z 
cwin � m  ef�y�y  � o      �x�x 0 final_target_window  ��  ��  ��   �  � � � ?  r{ �  � l ry�w�v I ry�u�t
�u .corecnte****       **** 2 ru�s
�s 
cwin�t  �w  �v    m  yz�r�r   � �q r  ~� 4 ~��p
�p 
cwin m  ���o�o  o      �n�n 0 final_target_window  �q  ��   � R      �m�l
�m .ascrerr ****      � **** o      �k�k 0 	class_err  �l   � k  �� 	
	 I ���j�i
�j .ascrcmnt****      � **** b  �� m  �� � � A S _ E r r o r   ( a c t i v a t e _ o r _ c r e a t e ) :   E r r o r   g e t t i n g   t a r g e t   w i n d o w   a f t e r   c r e a t i o n :   o  ���h�h 0 	class_err  �i  
 �g Z ���f�e ?  �� l ���d�c I ���b�a
�b .corecnte****       **** 2 ���`
�` 
cwin�a  �d  �c   m  ���_�_   r  �� 4 ���^
�^ 
cwin m  ���]�]  o      �\�\ 0 final_target_window  �f  �e  �g   �  l ���[�Z�Y�[  �Z  �Y   �X Z  ��W > �� !  o  ���V�V 0 final_target_window  ! m  ���U
�U 
msng k  �"" #$# I ���T%�S
�T .ascrcmnt****      � ****% m  ��&& �'' d A S :   S t y l i n g   n e w   w i n d o w   ' { { e s c a p e d _ t a r g e t _ t i t l e } } ' .�S  $ (�R( O  �)*) k  �++ ,-, r  ��./. m  ��00 �11 0 { { e s c a p e d _ d e v i c e _ l a b e l } }/ 1  ���Q
�Q 
titl- 232 r  ��454 J  ��66 7�P7 J  ��88 9�O9 o  ���N�N 0 aps_bg_color  �O  �P  5 1  ���M
�M 
pbcl3 :;: r  ��<=< J  ��>> ?�L? J  ��@@ A�KA o  ���J�J 0 aps_text_color  �K  �L  = 1  ���I
�I 
ptxc; BCB r  ��DED J  ��FF G�HG J  ��HH I�GI o  ���F�F 0 aps_text_color  �G  �H  E 1  ���E
�E 
pcucC JKJ r  �
LML J  �NN O�DO J  �PP Q�CQ o  � �B�B 0 aps_text_color  �C  �D  M 1  	�A
�A 
pbtcK R�@R r  STS m  �?�? T 1  �>
�> 
pidx�@  * o  ���=�= 0 final_target_window  �R  �W   I �<U�;
�< .ascrcmnt****      � ****U m  VV �WW � A S :   C o u l d   n o t   d e t e r m i n e   w i n d o w   f o r   s t y l i n g   ' { { e s c a p e d _ d e v i c e _ l a b e l } } ' .�;  �X  ��   2 m     XX�                                                                                      @ alis    J  Macintosh HD               㧉BD ����Terminal.app                                                   ����㧉        ����  
 cu             	Utilities   -/:System:Applications:Utilities:Terminal.app/     T e r m i n a l . a p p    M a c i n t o s h   H D  *System/Applications/Utilities/Terminal.app  / ��  ��  ��  ��       �:YZ�:  Y �9
�9 .aevtoappnull  �   � ****Z �8[�7�6\]�5
�8 .aevtoappnull  �   � ****[ k    ^^  /�4�4  �7  �6  \ �3�2�1�0�3 	0 w_obj  �2 0 find_err  �1 0 errmsg errMsg�0 0 	class_err  ] 3X�/�.�-�,�+�*�)�(�' M�&�% ]�$�# m�" � � � � � ��!� � � �� �� � ��������&0������V
�/ .miscactvnull��� ��� null
�. 
msng�- 0 window_to_use  �, 0 found_existing_window  
�+ 
cwin
�* 
kocl
�) 
cobj
�( .corecnte****       ****
�' 
titl�& 0 find_err  �%  
�$ .ascrcmnt****      � ****
�# 
bool
�" 
pidx
�! 
kfil
�  
tcnt
� .coredoscnull��� ��� ctxt� 0 new_terminal_entity  � 0 errmsg errMsg
� .sysodelanull��� ��� nmbr� 0 final_target_window  
� 
pcls� 0 new_entity_class  
� 
ttab�  � 0 	class_err  � 0 aps_bg_color  
� 
pbcl� 0 aps_text_color  
� 
ptxc
� 
pcuc
� 
pbtc�5�*j O�E�OfE�O 1 +*�-[��l kh  ��,�  �E�OeE�OY h[OY��W X  ��%j O�	 ���& ^a j O� *j Ok*a ,FUOa a   /a a  !a j O� a a *a ,l UY hY 	a j Yfa j O�E` O a j E` W X  a  �%j Oa !j "O�E` #O �_ � t_ a $,E` %O_ %a &  1 _ �,E` #W X ' *�-j j *�k/E` #Y hY ,_ %�  _ E` #Y *�-j j *�k/E` #Y hY *�-j j *�k/E` #Y hW )X ( a )�%j O*�-j j *�k/E` #Y hO_ #� [a *j O_ # Ia +*�,FO_ ,kvkv*a -,FO_ .kvkv*a /,FO_ .kvkv*a 0,FO_ .kvkv*a 1,FOk*a ,FUY 	a 2j U ascr  ��ޭ